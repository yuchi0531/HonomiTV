import httpx
from fastapi import HTTPException, status

from app import logging, schemas
from app.models.AnnictEpisodeRecord import AnnictEpisodeRecord
from app.models.RecordedProgram import RecordedProgram
from app.models.Series import Series
from app.models.User import User
from app.utils.AnnictClient import AnnictClient
from app.utils.SeriesMatcher import SeriesMatcher


async def CreateAnnictEpisodeRecord(access_token: str, episode_id: int) -> int:
    """
    Annict のエピソードへ視聴記録を作成する。

    Annict には Bangumi の「看過」に相当するエピソード単位のフラグが無く、record の作成が視聴記録になる。
    そのため同じエピソードへ二重に投稿しないよう、呼び出し側で台帳を確認すること。

    Args:
        access_token (str): Annict の個人用アクセストークン。
        episode_id (int): 記録する Annict のエピソード ID。

    Returns:
        int: 作成された record の ID。

    Raises:
        HTTPException: 接続失敗、スコープ不足、認証失効、または応答形式の不正。
    """

    try:
        return await AnnictClient.createEpisodeRecord(access_token, episode_id)
    except (httpx.NetworkError, httpx.TimeoutException) as ex:
        logging.error('[AnnictPlaybackSync][CreateAnnictEpisodeRecord] Failed to connect to Annict API.')
        raise HTTPException(
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE,
            detail = 'Failed to connect to Annict API',
        ) from ex
    except httpx.HTTPStatusError as ex:
        # 401 はトークン失効、403 はスコープ不足 (読み込み専用のトークンで投稿しようとした)
        if ex.response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]:
            logging.warning('[AnnictPlaybackSync][CreateAnnictEpisodeRecord] Annict access token is invalid or read-only.')
            raise HTTPException(
                status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail = 'Annict access token is invalid or does not have write permission',
            ) from ex
        logging.error(
            f'[AnnictPlaybackSync][CreateAnnictEpisodeRecord] Annict API returned HTTP {ex.response.status_code}.',
        )
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail = f'Failed to create Annict episode record (HTTP Error {ex.response.status_code})',
        ) from ex
    except ValueError as ex:
        logging.error('[AnnictPlaybackSync][CreateAnnictEpisodeRecord] Annict response was invalid.', exc_info=ex)
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail = 'Annict returned an invalid record response',
        ) from ex


async def SyncAnnictPlaybackProgress(
    video_id: int, progress_request: schemas.BangumiPlaybackProgressRequest, current_user: User,
) -> schemas.BangumiPlaybackProgressResponse:
    """
    現在の再生位置を所有するユーザーの Annict 視聴記録へ反映する。

    Args:
        video_id (int): 今回再生中の録画 ID。
        progress_request (schemas.BangumiPlaybackProgressRequest): 現在位置と解決済み時間。
        current_user (User): 認証済みの所有ユーザー。

    Returns:
        schemas.BangumiPlaybackProgressResponse: 対象話の同期結果。
    """

    if current_user.annict_user_id is None or current_user.annict_access_token is None:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Annict account is not linked',
        )

    recorded_program = await RecordedProgram.get_or_none(id=video_id).prefetch_related('recorded_video', 'channel')
    if recorded_program is None:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail = 'Specified video_id was not found',
        )

    # 完了判定はプロバイダ非依存なので、Bangumi と同じロジックを共有する
    episode_number, is_range, is_completed = SeriesMatcher.selectPlaybackEpisode(
        recorded_program, progress_request.playback_position, progress_request.duration,
    )
    if episode_number is None:
        return schemas.BangumiPlaybackProgressResponse(status='NotEligible')
    # 連続放送 (範囲録画) は 1 本の録画から複数話を切り出す必要があり、Annict の record とは相性が悪い.
    ## 誤った話へ記録するより、記録しない方が安全なので対象外とする
    if is_range:
        return schemas.BangumiPlaybackProgressResponse(status='NotEligible')
    if not is_completed or recorded_program.recorded_video.status != 'Recorded':
        return schemas.BangumiPlaybackProgressResponse(status='Pending')

    series = await Series.get_or_none(id=recorded_program.series_id) if recorded_program.series_id is not None else None
    if series is None or series.annict_work_id is None:
        return schemas.BangumiPlaybackProgressResponse(status='NotEligible')

    access_token = current_user.decryptAnnictAccessToken()

    # 既に記録済みのエピソードは重複投稿しない (Annict の record は公開ログになるため特に重要)
    try:
        episode_id = await AnnictClient.resolveRecordedEpisode(recorded_program, series, access_token)
    except (httpx.HTTPError, ValueError) as ex:
        logging.warning('[AnnictPlaybackSync][SyncAnnictPlaybackProgress] Episode resolution failed.', exc_info=ex)
        return schemas.BangumiPlaybackProgressResponse(status='Pending')
    if episode_id is None:
        logging.info(
            f'[AnnictPlaybackSync][SyncAnnictPlaybackProgress] Annict episode is not mapped. [video_id: {video_id}]',
        )
        return schemas.BangumiPlaybackProgressResponse(status='Pending')

    # 重播や複数タブからの重複更新を避けるため、記録済みかどうかを先に確認する
    if await AnnictEpisodeRecord.filter(
        user_id = current_user.id,
        annict_episode_id = episode_id,
    ).exists():
        return schemas.BangumiPlaybackProgressResponse(status='AlreadyCompleted')

    # 外部投稿に成功した後で台帳を作り、失敗を成功として扱わない
    record_id = await CreateAnnictEpisodeRecord(access_token, episode_id)
    await AnnictEpisodeRecord.get_or_create(
        user_id = current_user.id,
        annict_episode_id = episode_id,
        defaults = {
            'annict_record_id': record_id,
            'source_recorded_program_id': recorded_program.id,
        },
    )
    logging.info(
        f'[AnnictPlaybackSync][SyncAnnictPlaybackProgress] Created Annict record. '
        f'[konomitv_user_id: {current_user.id}, video_id: {video_id}, '
        f'annict_episode_id: {episode_id}, annict_record_id: {record_id}]',
    )
    return schemas.BangumiPlaybackProgressResponse(status='Completed')


async def SyncAnnictHistoryPlaybackProgress(
    current_user: User, playback_progress: schemas.HistoryPlaybackProgress | None,
) -> None:
    """
    履歴同期に明示された現在の再生位置だけを処理し、履歴保存とは障害を分離する。

    Args:
        current_user (User): 履歴を保存した認証済みユーザー。
        playback_progress (schemas.HistoryPlaybackProgress | None): 現在の再生報告。履歴一括移行では None。

    Returns:
        None: 未連携や外部投稿の失敗でも履歴保存の成功を保持する。
    """

    # 自動記録はユーザーが明示的に有効化した場合だけ行う
    ## Annict の record は公開の視聴ログになるため、既定では投稿しない
    if playback_progress is None or current_user.annict_user_id is None or current_user.annict_access_token is None:
        return
    if current_user.annict_auto_record_playback is False:
        return
    try:
        await SyncAnnictPlaybackProgress(playback_progress.video_id, playback_progress, current_user)
    except (httpx.HTTPError, HTTPException, ValueError) as ex:
        logging.warning(
            f'[AnnictPlaybackSync] Failed to sync current playback. [video_id: {playback_progress.video_id}]',
            exc_info = ex,
        )
