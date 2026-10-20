from typing import Annotated

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from app import logging, schemas
from app.models.Series import Series
from app.models.User import User
from app.routers.UsersRouter import GetCurrentUser
from app.utils.AnnictClient import AnnictClient
from app.utils.AnnictPlaybackSync import SyncAnnictPlaybackProgress


# ルーター
router = APIRouter(
    tags = ['Annict'],
    prefix = '/api/annict',
)


@router.post(
    '/auth',
    summary = 'Annict 個人用アクセストークン認証 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def AnnictAuthAPI(
    auth_request: Annotated[schemas.AnnictAuthRequest, Body(description='Annict 認証リクエスト。')],
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    指定された個人用アクセストークンで Annict 連携を行い、ログイン中のユーザーアカウントへ紐づける。<br>
    JWT エンコードされたアクセストークンが Authorization: Bearer に設定されていないとアクセスできない。

    Args:
        auth_request (schemas.AnnictAuthRequest): Annict 個人用アクセストークン。
        current_user (User): ログイン中の KonomiTV ユーザー。

    Returns:
        None: 連携が完了した場合。

    Raises:
        HTTPException: Annict API への接続、認証、またはレスポンス形式の検証に失敗した場合。
    """

    # 前後の空白や改行はコピー時に混入しやすいため除去してから検証する
    access_token = auth_request.access_token.strip()
    if access_token == '':
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Annict access token is empty',
        )

    try:
        # トークンの有効性確認とプロフィール取得を同時に行う
        ## ref: https://wikino.app/s/annict/pages/370
        viewer = await AnnictClient.fetchViewer(access_token)
    except (httpx.NetworkError, httpx.TimeoutException) as ex:
        logging.error('[AnnictRouter][AnnictAuthAPI] Failed to get user information. (Connection Timeout)')
        raise HTTPException(
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE,
            detail = 'Failed to get Annict user information (Connection Timeout)',
        ) from ex
    except httpx.HTTPStatusError as ex:
        # 認証エラーは入力したトークンが無効であることをクライアントへ明示する
        if ex.response.status_code == status.HTTP_401_UNAUTHORIZED:
            logging.warning('[AnnictRouter][AnnictAuthAPI] Annict access token is invalid.')
            raise HTTPException(
                status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail = 'Annict access token is invalid',
            ) from ex
        # Annict API 側の障害や仕様外レスポンスを認証エラーと混同しない
        logging.error(
            f'[AnnictRouter][AnnictAuthAPI] Failed to get user information. '
            f'(HTTP Error {ex.response.status_code})',
        )
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail = f'Failed to get Annict user information (HTTP Error {ex.response.status_code})',
        ) from ex

    try:
        annict_user_id = int(viewer['id'])
        annict_user_name = str(viewer['username'])
        annict_user_nickname = str(viewer.get('name') or viewer['username'])
        annict_user_avatar_url = str(viewer.get('avatar_url') or '')
    except (KeyError, TypeError, ValueError) as ex:
        logging.error('[AnnictRouter][AnnictAuthAPI] Annict user information is invalid.', exc_info=ex)
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail = 'Annict user information is invalid',
        ) from ex

    # 外部 API の検証が完了してから、公開プロフィールと暗号化済みトークンをまとめて保存する
    current_user.annict_user_id = annict_user_id
    current_user.annict_user_name = annict_user_name
    current_user.annict_user_nickname = annict_user_nickname
    current_user.annict_user_avatar_url = annict_user_avatar_url
    current_user.annict_access_token = current_user.encryptAnnictAccessToken(access_token)
    await current_user.save(update_fields=[
        'annict_user_id', 'annict_user_name', 'annict_user_nickname',
        'annict_user_avatar_url', 'annict_access_token', 'updated_at',
    ])

    # 認証 API の応答を作品一覧のページングから切り離し、以後の照合をバックエンドだけで進める
    AnnictClient.scheduleUserWorkSync(current_user)

    logging.info(
        f'[AnnictRouter][AnnictAuthAPI] Linked Annict account. '
        f'[konomitv_user_id: {current_user.id}, annict_user_id: {annict_user_id}]',
    )


@router.post(
    '/videos/{video_id}/progress',
    summary = 'Annict 録画視聴進捗 API',
    response_model = schemas.BangumiPlaybackProgressResponse,
    status_code = status.HTTP_200_OK,
)
async def AnnictPlaybackProgressAPI(
    video_id: Annotated[int, Path(description='視聴中の録画番組 ID。')],
    progress_request: Annotated[schemas.BangumiPlaybackProgressRequest, Body(description='録画視聴進捗。')],
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    指定した録画番組の視聴進捗を受け取り、完了位置到達後に照合済み Annict エピソードへ視聴記録を作成する。<br>
    JWT エンコードされたアクセストークンが Authorization: Bearer に設定されていないとアクセスできない。

    Args:
        video_id (int): 視聴中の録画番組 ID。
        progress_request (schemas.BangumiPlaybackProgressRequest): プレイヤーが解決した再生位置と録画時間。
        current_user (User): ログイン中の KonomiTV ユーザー。

    Returns:
        schemas.BangumiPlaybackProgressResponse: 同期処理の結果。

    Raises:
        HTTPException: 録画番組が存在しない、連携がない、または Annict API の更新に失敗した場合。
    """

    return await SyncAnnictPlaybackProgress(video_id, progress_request, current_user)


@router.put(
    '/auto-record',
    summary = 'Annict 自動記録設定 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def AnnictAutoRecordAPI(
    request: Annotated[schemas.AnnictAutoRecordRequest, Body(description='視聴記録の自動投稿設定。')],
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    Annict へ視聴記録を自動投稿するかどうかを設定する。<br>
    record は公開の視聴ログになるため、明示的に有効化された場合だけ投稿する。<br>
    JWT エンコードされたアクセストークンが Authorization: Bearer に設定されていないとアクセスできない。

    Args:
        request (schemas.AnnictAutoRecordRequest): 自動投稿の有効・無効。
        current_user (User): ログイン中の KonomiTV ユーザー。

    Returns:
        None: 設定が完了した場合。
    """

    current_user.annict_auto_record_playback = request.enabled
    await current_user.save(update_fields=['annict_auto_record_playback', 'updated_at'])

    logging.info(
        f'[AnnictRouter][AnnictAutoRecordAPI] Updated auto record setting. '
        f'[konomitv_user_id: {current_user.id}, enabled: {request.enabled}]',
    )


@router.delete(
    '/logout',
    summary = 'Annict アカウント連携解除 API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def AnnictAccountLogoutAPI(
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    現在ログイン中のユーザーアカウントに紐づく Annict アカウントとの連携を解除する。<br>
    JWT エンコードされたアクセストークンが Authorization: Bearer に設定されていないとアクセスできない。

    Args:
        current_user (User): ログイン中の KonomiTV ユーザー。

    Returns:
        None: 連携解除が完了した場合。
    """

    # 公開プロフィールと認証情報をすべて消去し、部分的な連携状態を残さない
    current_user.annict_user_id = None
    current_user.annict_user_name = None
    current_user.annict_user_nickname = None
    current_user.annict_user_avatar_url = None
    current_user.annict_access_token = None
    await current_user.save(update_fields=[
        'annict_user_id', 'annict_user_name', 'annict_user_nickname',
        'annict_user_avatar_url', 'annict_access_token', 'updated_at',
    ])

    logging.info(
        f'[AnnictRouter][AnnictAccountLogoutAPI] Unlinked Annict account. [konomitv_user_id: {current_user.id}]',
    )

@router.get(
    '/unlinked-series',
    summary = 'Annict 未紐づけシリーズ一覧 API',
    response_description = 'Annict 作品と紐づいていないシリーズの一覧。',
    response_model = schemas.AnnictUnlinkedSeriesList,
)
async def AnnictUnlinkedSeriesAPI(
    current_user: Annotated[User, Depends(GetCurrentUser)],
):
    """
    Annict 作品と紐づいていないシリーズの一覧を返す。

    自動照合で紐づかなかったシリーズを手動で紐づけるために使う。
    """

    if current_user.annict_user_id is None or current_user.annict_access_token is None:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Annict account is not linked',
        )

    # Annict へ紐づけできるジャンルの Series だけを対象にする
    eligible_series = [
        series for series in await Series.all()
        if any(genre['major'] in AnnictClient.ELIGIBLE_GENRES for genre in series.genres)
    ]
    return schemas.AnnictUnlinkedSeriesList(
        series_list = [
            schemas.AnnictUnlinkedSeries(
                id = series.id,
                title = series.title,
                annict_work_id = series.annict_work_id,
                annict_work_name = series.annict_work_name,
            )
            for series in eligible_series
            if series.annict_work_id is None
        ],
    )


@router.get(
    '/works/search',
    summary = 'Annict 作品検索 API',
    response_description = '検索条件に一致した Annict の作品一覧。',
    response_model = schemas.AnnictWorkCandidates,
)
async def AnnictWorkSearchAPI(
    current_user: Annotated[User, Depends(GetCurrentUser)],
    query: Annotated[str, Query(min_length=1, description='検索する作品タイトル。')],
):
    """
    Annict に登録されている作品をタイトルで検索する。

    手動紐づけの候補を選ぶために使う。
    """

    if current_user.annict_access_token is None:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Annict account is not linked',
        )

    access_token = current_user.decryptAnnictAccessToken()
    try:
        works = await AnnictClient.searchWorksByTitle(access_token, query)
    except (httpx.HTTPError, ValueError) as ex:
        logging.warning('[AnnictRouter][AnnictWorkSearchAPI] Failed to search Annict works.', exc_info=ex)
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail = 'Failed to search Annict works',
        ) from ex

    # 詳細 (話数など) は検索結果に含まれないため、タイトルだけで返す
    return schemas.AnnictWorkCandidates(
        works = [
            schemas.AnnictWorkCandidate_Schema(
                id = work['id'],
                title = (work['titles'] or [''])[0],
                title_kana = (work['titles'] or [None, None, None])[2],
                title_en = (work['titles'] or [None, None])[1],
                episodes_count = None,
            )
            for work in works
        ],
    )


@router.put(
    '/series/{series_id}/link',
    summary = 'Annict 作品手動紐づけ API',
    status_code = status.HTTP_204_NO_CONTENT,
)
async def AnnictSeriesLinkAPI(
    current_user: Annotated[User, Depends(GetCurrentUser)],
    series_id: Annotated[int, Path(description='シリーズ番組の ID 。')],
    link_request: Annotated[schemas.AnnictSeriesLinkRequest, Body(description='紐づける Annict 作品の ID 。')],
):
    """
    シリーズを Annict 作品へ手動で紐づける。

    自動照合で紐づかなかったシリーズを、利用者が明示的に指定するために使う。
    """

    if current_user.annict_access_token is None:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Annict account is not linked',
        )

    series = await Series.get_or_none(id=series_id)
    if series is None:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Specified series_id was not found',
        )

    # Annict 作品 ID は一意なので、同じ作品に複数の Series が紐づかないよう確認する
    conflict = await Series.get_or_none(annict_work_id=link_request.annict_work_id)
    if conflict is not None and conflict.id != series.id:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Specified Annict work is already linked to another series',
        )

    # 作品名を取得して保存する (取得できなくても ID だけで紐づけは成立する)
    access_token = current_user.decryptAnnictAccessToken()
    work_name = series.title
    try:
        works = await AnnictClient.searchWorksByTitle(access_token, series.title)
        matched = next((work for work in works if work['id'] == link_request.annict_work_id), None)
        if matched is not None and len(matched['titles']) > 0:
            work_name = matched['titles'][0]
    except (httpx.HTTPError, ValueError) as ex:
        # 作品名が取れなくても紐づけ自体は行う
        logging.warning('[AnnictRouter][AnnictSeriesLinkAPI] Failed to resolve the work title.', exc_info=ex)

    series.annict_work_id = link_request.annict_work_id
    series.annict_work_name = work_name
    await series.save(update_fields=['annict_work_id', 'annict_work_name'])
    logging.info(
        f'[AnnictRouter][AnnictSeriesLinkAPI] Linked series to Annict work. '
        f'[series_id: {series.id}, annict_work_id: {link_request.annict_work_id}]',
    )
