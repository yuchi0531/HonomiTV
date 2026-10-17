from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from time import monotonic
from typing import Any, cast
from weakref import WeakValueDictionary

import httpx
from typing_extensions import TypedDict

from app import logging
from app.constants import API_REQUEST_HEADERS, HTTPX_CLIENT
from app.models.RecordedProgram import RecordedProgram
from app.models.Series import Series
from app.models.User import User
from app.utils.SeriesMatcher import SeriesMatcher


class AnnictWorkCandidate(TypedDict):
    """Annict の作品を照合に使うための最小限の情報。"""

    # Annict の作品 ID
    id: int
    # 照合に使うタイトル候補 (原題・英語表記)
    titles: list[str]


class AnnictClient:
    """KonomiTV の録画番組を Annict の作品とエピソードへ照合する。"""

    # Annict REST API V1 のベース URL
    ## ref: https://wikino.app/s/annict/pages/363
    API_BASE_URL = 'https://api.annict.com/v1'
    # 1 ページあたりの取得件数 (Annict API の上限は 50)
    PAGE_SIZE = 50
    # 照合対象とする EPG ジャンル
    ## Bangumi と同じく、既に Series として整理された連続番組だけを対象にする
    ELIGIBLE_GENRES = {'アニメ・特撮', 'ドラマ', 'ドキュメンタリー・教養', 'バラエティ', '音楽'}
    # 視聴中・視聴済みとして候補に含めるステータス
    CANDIDATE_STATUSES = ('watching', 'watched')
    # 読み取り結果のキャッシュ設定
    ## 認証ごとに隔離し、公開範囲の違うアカウントへ応答を流用しない。token は保持せずハッシュだけをキーに使う。
    READ_CACHE_TTL_SECONDS = 300
    READ_CACHE_MAX_ENTRIES = 256
    _read_cache: OrderedDict[tuple[str, str, tuple[tuple[str, str], ...]], tuple[float, Any]] = OrderedDict()
    _read_locks: WeakValueDictionary[tuple[str, str, tuple[tuple[str, str], ...]], asyncio.Lock] = WeakValueDictionary()
    # アカウント連携直後の同期タスクへの強参照
    _sync_tasks: set[asyncio.Task[None]] = set()


    @classmethod
    async def _getCachedJSON(
        cls, client: httpx.AsyncClient, url: str, access_token: str,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        """
        認証付きの Annict API 読み取りを期限と容量付きでキャッシュする。

        Args:
            client (httpx.AsyncClient): 呼び出し元が管理する HTTP クライアント。
            url (str): 読み取り先 URL。
            access_token (str): 連携アカウントのアクセストークン。
            params (dict[str, str | int] | None): ページ指定などのクエリ。

        Returns:
            dict[str, Any]: 呼び出し元の変更がキャッシュへ波及しない JSON のコピー。

        Raises:
            httpx.HTTPError: 取得に失敗した場合。失敗応答はキャッシュしない。
        """

        key = (
            sha256(access_token.encode()).hexdigest(),
            url,
            tuple(sorted((str(name), str(value)) for name, value in (params or {}).items())),
        )
        lock = cls._read_locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = monotonic()
            # 期限切れの応答を削除し、認証失効や新着を定期的に再検証する
            for expired_key, (expires_at, _) in list(cls._read_cache.items()):
                if expires_at <= now:
                    del cls._read_cache[expired_key]
            if key in cls._read_cache:
                cls._read_cache.move_to_end(key)
                return cast(dict[str, Any], deepcopy(cls._read_cache[key][1]))

            response = await client.get(
                url = url,
                headers = cls._buildHeaders(access_token),
                params = params,
            )
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())

            # 成功した JSON だけ保存し、最近使われていない項目から容量上限まで追い出す
            cls._read_cache[key] = (monotonic() + cls.READ_CACHE_TTL_SECONDS, deepcopy(payload))
            while len(cls._read_cache) > cls.READ_CACHE_MAX_ENTRIES:
                cls._read_cache.popitem(last=False)
            return payload


    @staticmethod
    def _buildHeaders(access_token: str) -> dict[str, str]:
        """
        Annict API 用のリクエストヘッダーを組み立てる。

        Args:
            access_token (str): Annict の個人用アクセストークン。

        Returns:
            dict[str, str]: 認証ヘッダー付きのリクエストヘッダー。
        """

        # アクセストークンはクエリではなくヘッダーで渡し、アクセスログやブラウザ履歴へ残さない
        ## ref: https://wikino.app/s/annict/pages/363
        return {**API_REQUEST_HEADERS, 'Authorization': f'Bearer {access_token}'}


    @classmethod
    async def fetchViewer(cls, access_token: str) -> dict[str, Any]:
        """
        個人用アクセストークンの有効性を確認し、連携先のプロフィールを取得する。

        Args:
            access_token (str): Annict の個人用アクセストークン。

        Returns:
            dict[str, Any]: `GET /v1/me` のレスポンス。

        Raises:
            httpx.HTTPError: 認証または取得に失敗した場合。
        """

        async with HTTPX_CLIENT() as client:
            response = await client.get(
                url = f'{cls.API_BASE_URL}/me',
                headers = cls._buildHeaders(access_token),
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())


    @classmethod
    async def _fetchPagedList(
        cls,
        access_token: str,
        path: str,
        list_key: str,
        params: dict[str, str | int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Annict のページネーション付き一覧を最終ページまで取得する。

        Args:
            access_token (str): Annict の個人用アクセストークン。
            path (str): API のパス (例: '/me/works')。
            list_key (str): レスポンスの一覧が入っているキー。
            params (dict[str, str | int] | None): 追加のクエリ。

        Returns:
            list[dict[str, Any]]: 全ページ分の一覧。

        Raises:
            httpx.HTTPError: 取得に失敗した場合。
        """

        results: list[dict[str, Any]] = []
        page = 1
        async with HTTPX_CLIENT() as client:
            while True:
                query: dict[str, str | int] = {**(params or {}), 'page': page, 'per_page': cls.PAGE_SIZE}
                payload = await cls._getCachedJSON(client, f'{cls.API_BASE_URL}{path}', access_token, query)
                page_items = cast(list[dict[str, Any]], payload.get(list_key) or [])
                results.extend(page_items)
                # next_page が null なら最終ページ。無限ループを避けるため件数 0 でも終了する
                ## ref: https://wikino.app/s/annict/pages/363
                if payload.get('next_page') is None or len(page_items) == 0:
                    break
                page = int(payload['next_page'])
        return results


    @classmethod
    async def fetchCandidateWorks(cls, access_token: str) -> list[AnnictWorkCandidate]:
        """
        連携ユーザーの「見てる」「見た」作品を照合候補として取得する。

        Args:
            access_token (str): Annict の個人用アクセストークン。

        Returns:
            list[AnnictWorkCandidate]: 重複を除いた作品候補のリスト。

        Raises:
            httpx.HTTPError: 取得に失敗した場合。
        """

        works: dict[int, AnnictWorkCandidate] = {}
        # status は 1 回のリクエストで複数指定できないため、対象のステータスごとに取得して統合する
        for status in cls.CANDIDATE_STATUSES:
            for work in await cls._fetchPagedList(access_token, '/me/works', 'works', {'filter_status': status}):
                work_id = int(work['id'])
                titles = [str(work.get('title') or ''), str(work.get('title_en') or ''), str(work.get('title_kana') or '')]
                works[work_id] = AnnictWorkCandidate(
                    id = work_id,
                    titles = [title for title in titles if title != ''],
                )
        return list(works.values())


    @classmethod
    async def fetchEpisodes(cls, access_token: str, work_id: int) -> list[dict[str, Any]]:
        """
        指定した作品のエピソード一覧を取得する。

        Args:
            access_token (str): Annict の個人用アクセストークン。
            work_id (int): Annict の作品 ID。

        Returns:
            list[dict[str, Any]]: 作品に属するエピソード。

        Raises:
            httpx.HTTPError: 取得に失敗した場合。
        """

        return await cls._fetchPagedList(access_token, '/episodes', 'episodes', {'filter_work_id': work_id})


    @staticmethod
    def findWork(series_title: str, works: list[AnnictWorkCandidate]) -> AnnictWorkCandidate | None:
        """
        ローカル Series に対応する Annict 作品を一意に選ぶ。

        Args:
            series_title (str): ローカル Series の表示タイトル。
            works (list[AnnictWorkCandidate]): 連携ユーザーの作品候補。

        Returns:
            AnnictWorkCandidate | None: 十分に一意な候補。決められない場合は None。
        """

        matched_id = SeriesMatcher.findBestCandidate(
            series_title,
            [(work['id'], (work['titles'] or [''])[0], work['titles']) for work in works],
        )
        if matched_id is None:
            return None
        return next((work for work in works if work['id'] == matched_id), None)


    @staticmethod
    def normalizeEpisodeNumber(episode: dict[str, Any]) -> int | None:
        """
        Annict のエピソードから照合に使う話数を取り出す。

        Annict の `sort_number` は 10 倍された値 (第 5 話なら 50) なので、10 で割って話数へ戻す。
        10 の倍数でない値は特別編など話数として扱えないため None を返す。

        Args:
            episode (dict[str, Any]): Annict のエピソード。

        Returns:
            int | None: 話数。話数として解釈できない場合は None。
        """

        sort_number = episode.get('sort_number')
        if sort_number is None:
            return None
        try:
            parsed_sort_number = int(sort_number)
        except (TypeError, ValueError):
            return None
        if parsed_sort_number <= 0 or parsed_sort_number % 10 != 0:
            return None
        return parsed_sort_number // 10


    @classmethod
    def findEpisode(cls, episodes: list[dict[str, Any]], episode_number: int) -> dict[str, Any] | None:
        """
        EPG 話数に対応する Annict のエピソードを一意に取得する。

        Args:
            episodes (list[dict[str, Any]]): 作品のエピソード一覧。
            episode_number (int): EPG から抽出した話数。

        Returns:
            dict[str, Any] | None: 一意に一致したエピソード。複数該当・該当なしの場合は None。
        """

        matched = [episode for episode in episodes if cls.normalizeEpisodeNumber(episode) == episode_number]
        if len(matched) != 1:
            return None
        return matched[0]


    @classmethod
    async def isRecordable(cls, access_token: str) -> bool:
        """
        アクセストークンが書き込み可能なスコープかどうかを確認する。

        Annict はスコープ不足の書き込みを 403 で返すため、実際の記録作成時に判定する。
        ここではトークンの有効性だけを確認する。

        Args:
            access_token (str): Annict の個人用アクセストークン。

        Returns:
            bool: トークンが有効なら True。
        """

        try:
            await cls.fetchViewer(access_token)
            return True
        except httpx.HTTPError:
            return False


    @classmethod
    async def createEpisodeRecord(
        cls,
        access_token: str,
        episode_id: int,
    ) -> int:
        """
        Annict のエピソードへ視聴記録を作成する。

        Args:
            access_token (str): Annict の個人用アクセストークン。
            episode_id (int): 記録する Annict のエピソード ID。

        Returns:
            int: 作成された record の ID。

        Raises:
            httpx.HTTPStatusError: スコープ不足 (403) や認証エラー (401) を含む API エラー。
            ValueError: 応答から record ID を取り出せない場合。
        """

        async with HTTPX_CLIENT() as client:
            response = await client.post(
                url = f'{cls.API_BASE_URL}/me/records',
                headers = cls._buildHeaders(access_token),
                params = {'episode_id': episode_id},
            )
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())

        # 応答は作成した record 1 件。ID が無い応答を成功として扱わない
        try:
            return int(payload['id'])
        except (KeyError, TypeError, ValueError) as ex:
            raise ValueError('Annict record response did not contain a record ID') from ex


    @classmethod
    async def resolveRecordedEpisode(
        cls,
        recorded_program: RecordedProgram,
        series: Series,
        access_token: str,
        episodes_by_work_id: dict[int, list[dict[str, Any]]] | None = None,
    ) -> int | None:
        """
        録画に対応する Annict のエピソード ID を解決する。

        Args:
            recorded_program (RecordedProgram): 照合する録画。
            series (Series): ローカル Series の主作品。
            access_token (str): 連携ユーザーのアクセストークン。
            episodes_by_work_id (dict[int, list[dict[str, Any]]] | None): 一括同期中だけ共有するエピソードキャッシュ。

        Returns:
            int | None: 解決した Annict エピソード ID。決められない場合は None。
        """

        if series.annict_work_id is None:
            return None
        episode_number = SeriesMatcher.parseEpisodeNumber(recorded_program.episode_number)
        if episode_number is None:
            return None

        cache = episodes_by_work_id if episodes_by_work_id is not None else {}
        if series.annict_work_id not in cache:
            cache[series.annict_work_id] = await cls.fetchEpisodes(access_token, series.annict_work_id)
        episode = cls.findEpisode(cache[series.annict_work_id], episode_number)
        if episode is None:
            return None
        return int(episode['id'])


    @classmethod
    async def syncUserWorks(cls, user: User) -> int:
        """
        連携ユーザーの作品一覧を候補としてローカル Series と照合する。

        Args:
            user (User): Annict アカウント連携済みの KonomiTV ユーザー。

        Returns:
            int: 今回 Annict 作品へ照合できた Series 数。

        Raises:
            httpx.HTTPError: Annict API への接続または HTTP エラーが発生した場合。
        """

        eligible_series = [
            series for series in await Series.all()
            if any(genre['major'] in cls.ELIGIBLE_GENRES for genre in series.genres)
        ]
        # ローカルに照合対象の Series が一件もなければ、Annict API 自体へアクセスしない
        if len(eligible_series) == 0:
            return 0

        access_token = user.decryptAnnictAccessToken()
        works = await cls.fetchCandidateWorks(access_token)
        matched_count = 0

        for series in eligible_series:
            # 先行する同期で削除された Series を再処理しない
            if await Series.filter(id=series.id).exists() is False:
                continue

            # 既に作品が確定している Series は、別の表記で上書きしない
            if series.annict_work_id is not None:
                work = next((candidate for candidate in works if candidate['id'] == series.annict_work_id), None)
            else:
                work = cls.findWork(series.title, works)
            if work is None:
                continue

            # Annict 作品 ID は一意なので、同じ作品に複数の Series が紐付かないよう確認する
            ## Annict には Bangumi の「条目統合」に相当する仕組みが無いため、既存 Series の統合は行わない
            conflict = await Series.get_or_none(annict_work_id=work['id'])
            if conflict is not None and conflict.id != series.id:
                logging.warning(
                    f'[AnnictClient][syncUserWorks] Annict work is already linked to another Series. '
                    f'[annict_work_id: {work["id"]}, series_id: {series.id}, linked_series_id: {conflict.id}]',
                )
                continue

            title = (work['titles'] or [''])[0] or series.title
            series.annict_work_id = work['id']
            series.annict_work_name = title
            await series.save(update_fields=['annict_work_id', 'annict_work_name'])
            matched_count += 1

        return matched_count


    @classmethod
    async def syncAllLinkedUsers(cls) -> None:
        """
        Annict 連携済みユーザーごとに作品一覧を取得し、ローカル Series へ反映する。

        Returns:
            None
        """

        users = await User.all().exclude(annict_user_name=None).exclude(annict_access_token=None)
        for user in users:
            try:
                matched_series_count = await cls.syncUserWorks(user)
                logging.info(
                    f'[AnnictClient][syncAllLinkedUsers] Synchronized Annict works. '
                    f'[konomitv_user_id: {user.id}, matched_series: {matched_series_count}]',
                )
            except (httpx.HTTPError, ValueError) as ex:
                logging.error(
                    f'[AnnictClient][syncAllLinkedUsers] Failed to synchronize Annict works. '
                    f'[konomitv_user_id: {user.id}]',
                    exc_info = ex,
                )


    @classmethod
    def scheduleUserWorkSync(cls, user: User) -> None:
        """
        アカウント連携直後の作品一覧同期を API レスポンスと切り離して開始する。

        Args:
            user (User): Annict アカウント連携済みの KonomiTV ユーザー。

        Returns:
            None
        """

        async def Sync() -> None:
            try:
                matched_series_count = await cls.syncUserWorks(user)
                logging.info(
                    f'[AnnictClient][scheduleUserWorkSync] Synchronized Annict works. '
                    f'[konomitv_user_id: {user.id}, matched_series: {matched_series_count}]',
                )
            except (httpx.HTTPError, ValueError) as ex:
                logging.error(
                    f'[AnnictClient][scheduleUserWorkSync] Failed to synchronize Annict works. '
                    f'[konomitv_user_id: {user.id}]',
                    exc_info = ex,
                )

        # 実行中タスクへの強参照を保持し、完了時だけ集合から取り除く
        task = asyncio.create_task(Sync())
        cls._sync_tasks.add(task)
        task.add_done_callback(cls._sync_tasks.discard)

