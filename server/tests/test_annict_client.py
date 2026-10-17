import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.models.Series import Series
from app.utils.AnnictClient import AnnictClient
from app.utils.SeriesMatcher import SeriesMatcher


def Work(work_id: int, *titles: str) -> dict[str, Any]:
    """
    Annict の作品候補を組み立てる。

    Args:
        work_id (int): 作品 ID。
        *titles (str): 照合に使うタイトル。

    Returns:
        dict[str, Any]: 作品候補。
    """

    return {'id': work_id, 'titles': [title for title in titles if title]}


class AnnictEpisodeNumberTest(unittest.TestCase):
    """Annict のエピソード番号の正規化を検証する。"""

    def test_sort_number_is_divided_by_ten(self) -> None:
        """sort_number は 10 倍された通算話数なので、10 で割って話数へ戻す。"""

        # 第 1 話は sort_number 10、第 12 話は 120 になる
        self.assertEqual(AnnictClient.normalizeEpisodeNumber({'sort_number': 10}), 1)
        self.assertEqual(AnnictClient.normalizeEpisodeNumber({'sort_number': 120}), 12)

    def test_non_multiple_of_ten_is_not_an_episode_number(self) -> None:
        """特別編など 10 の倍数でない値は話数として扱わない。"""

        for sort_number in (0, 5, 15, 99, -10):
            with self.subTest(sort_number=sort_number):
                self.assertIsNone(AnnictClient.normalizeEpisodeNumber({'sort_number': sort_number}))

    def test_missing_or_invalid_sort_number_is_ignored(self) -> None:
        """sort_number が無い・数値でない場合は None を返す。"""

        self.assertIsNone(AnnictClient.normalizeEpisodeNumber({}))
        self.assertIsNone(AnnictClient.normalizeEpisodeNumber({'sort_number': None}))
        self.assertIsNone(AnnictClient.normalizeEpisodeNumber({'sort_number': 'abc'}))

    def test_find_episode_requires_a_unique_match(self) -> None:
        """話数が一意に一致する場合だけエピソードを返す。"""

        episodes = [
            {'id': 501, 'sort_number': 10, 'title': '第1話'},
            {'id': 502, 'sort_number': 20, 'title': '第2話'},
        ]
        self.assertEqual(AnnictClient.findEpisode(episodes, 2)['id'], 502)
        self.assertIsNone(AnnictClient.findEpisode(episodes, 3))
        # 同じ話数が複数ある場合は誤って選ばない
        self.assertIsNone(AnnictClient.findEpisode([*episodes, {'id': 503, 'sort_number': 20}], 2))


class AnnictWorkMatchingTest(unittest.TestCase):
    """Annict 作品との照合を検証する。"""

    def test_exact_title_matches(self) -> None:
        """完全一致する作品を選ぶ。"""

        works = [Work(1, '作品A'), Work(2, '作品B')]
        self.assertEqual(AnnictClient.findWork('作品A', works)['id'], 1)

    def test_english_title_is_also_a_candidate(self) -> None:
        """英語表記でも一致すれば選ぶ。"""

        works = [Work(1, '作品A', 'Work A')]
        self.assertEqual(AnnictClient.findWork('Work A', works)['id'], 1)

    def test_ambiguous_candidates_are_not_selected(self) -> None:
        """同点に近い候補が複数ある場合は自動確定しない。"""

        works = [Work(1, '同じ名前'), Work(2, '同じ名前')]
        self.assertIsNone(AnnictClient.findWork('同じ名前', works))

    def test_unrelated_title_is_not_selected(self) -> None:
        """無関係な作品へは紐付けない。"""

        self.assertIsNone(AnnictClient.findWork('まったく別の作品', [Work(1, '作品A')]))


class AnnictClientAPITest(unittest.IsolatedAsyncioTestCase):
    """Annict API 呼び出しの契約を検証する。"""

    async def asyncSetUp(self) -> None:
        """
        キャッシュを初期化し、テスト間で応答を共有しない。

        Returns:
            None
        """

        AnnictClient._read_cache.clear()

    async def test_fetch_viewer_uses_bearer_header(self) -> None:
        """個人用アクセストークンはクエリではなく Authorization ヘッダーで送る。"""

        response = MagicMock()
        response.json.return_value = {'id': 7, 'username': 'viewer', 'name': 'Viewer'}
        response.raise_for_status.return_value = None
        client = AsyncMock()
        client.get.return_value = response
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with patch('app.utils.AnnictClient.HTTPX_CLIENT', return_value=client):
            viewer = await AnnictClient.fetchViewer('token-value')

        self.assertEqual(viewer['id'], 7)
        call = client.get.call_args
        self.assertTrue(call.kwargs['headers']['Authorization'] == 'Bearer token-value')
        # トークンを URL へ載せない
        self.assertNotIn('token-value', call.kwargs['url'])
        self.assertNotIn('access_token', call.kwargs.get('params') or {})

    async def test_paged_list_follows_next_page(self) -> None:
        """next_page が null になるまで全ページを取得する。"""

        payloads = [
            {'works': [{'id': 1, 'title': 'A'}], 'next_page': 2},
            {'works': [{'id': 2, 'title': 'B'}], 'next_page': None},
        ]
        with patch.object(AnnictClient, '_getCachedJSON', AsyncMock(side_effect=payloads)):
            items = await AnnictClient._fetchPagedList('token', '/me/works', 'works')

        self.assertEqual([item['id'] for item in items], [1, 2])

    async def test_empty_page_terminates_pagination(self) -> None:
        """next_page が残っていても空ページで打ち切り、無限ループを避ける。"""

        payloads = [{'works': [], 'next_page': 2}]
        with patch.object(AnnictClient, '_getCachedJSON', AsyncMock(side_effect=payloads)):
            items = await AnnictClient._fetchPagedList('token', '/me/works', 'works')

        self.assertEqual(items, [])

    async def test_candidate_works_merges_statuses(self) -> None:
        """「見てる」「見た」の両方を候補にし、同じ作品を重複させない。"""

        async def fake_fetch(_token: str, _path: str, _key: str, params: dict[str, Any] | None = None):
            if params and params.get('filter_status') == 'watching':
                return [{'id': 1, 'title': '作品A', 'title_en': 'A'}]
            return [{'id': 1, 'title': '作品A', 'title_en': 'A'}, {'id': 2, 'title': '作品B'}]

        with patch.object(AnnictClient, '_fetchPagedList', AsyncMock(side_effect=fake_fetch)):
            works = await AnnictClient.fetchCandidateWorks('token')

        self.assertEqual(sorted(work['id'] for work in works), [1, 2])
        work_a = next(work for work in works if work['id'] == 1)
        self.assertEqual(work_a['titles'], ['作品A', 'A'])

    async def test_create_record_returns_record_id(self) -> None:
        """記録作成 API の応答から record ID を取り出す。"""

        response = MagicMock()
        response.json.return_value = {'id': 425551, 'episode': {'id': 501}}
        response.raise_for_status.return_value = None
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with patch('app.utils.AnnictClient.HTTPX_CLIENT', return_value=client):
            record_id = await AnnictClient.createEpisodeRecord('token', 501)

        self.assertEqual(record_id, 425551)
        call = client.post.call_args
        self.assertTrue(call.kwargs['params'] == {'episode_id': 501})

    async def test_create_record_rejects_response_without_id(self) -> None:
        """record ID が無い応答を成功として扱わない。"""

        response = MagicMock()
        response.json.return_value = {'unexpected': True}
        response.raise_for_status.return_value = None
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with patch('app.utils.AnnictClient.HTTPX_CLIENT', return_value=client):
            with self.assertRaises(ValueError):
                await AnnictClient.createEpisodeRecord('token', 501)

    async def test_write_errors_propagate_as_http_status_error(self) -> None:
        """403 (読み込み専用トークン) は呼び出し側が判別できる例外として伝播する。"""

        request = httpx.Request('POST', 'https://api.annict.com/v1/me/records')
        response = httpx.Response(403, request=request)
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with patch('app.utils.AnnictClient.HTTPX_CLIENT', return_value=client):
            with self.assertRaises(httpx.HTTPStatusError) as context:
                await AnnictClient.createEpisodeRecord('token', 501)

        self.assertEqual(context.exception.response.status_code, 403)


class AnnictSyncSkipTest(unittest.IsolatedAsyncioTestCase):
    """自動記録が既定で無効であることを検証する。"""

    async def test_auto_record_is_disabled_by_default(self) -> None:
        """User の既定値では Annict へ書き込まない。"""

        # DB を経由せずモデルの既定値を確認する (サーバーが投稿する設定のため User のカラムにある)
        from app.models.User import User

        self.assertIs(User._meta.fields_map['annict_auto_record_playback'].default, False)

    async def test_sync_is_skipped_when_auto_record_is_off(self) -> None:
        """自動記録がオフなら、連携済みでも投稿処理を呼ばない。"""

        from app.utils.AnnictPlaybackSync import SyncAnnictHistoryPlaybackProgress

        user = MagicMock()
        user.annict_user_id = 1
        user.annict_access_token = 'encrypted'
        user.annict_auto_record_playback = False
        progress = MagicMock(video_id=1)

        with patch('app.utils.AnnictPlaybackSync.SyncAnnictPlaybackProgress', AsyncMock()) as sync:
            await SyncAnnictHistoryPlaybackProgress(user, progress)

        sync.assert_not_awaited()

    async def test_sync_runs_when_auto_record_is_on(self) -> None:
        """自動記録がオンなら投稿処理を呼ぶ。"""

        from app.utils.AnnictPlaybackSync import SyncAnnictHistoryPlaybackProgress

        user = MagicMock()
        user.annict_user_id = 1
        user.annict_access_token = 'encrypted'
        user.annict_auto_record_playback = True
        progress = MagicMock(video_id=1)

        with patch('app.utils.AnnictPlaybackSync.SyncAnnictPlaybackProgress', AsyncMock()) as sync:
            await SyncAnnictHistoryPlaybackProgress(user, progress)

        sync.assert_awaited_once()

    async def test_sync_is_skipped_when_progress_is_missing(self) -> None:
        """再生位置の報告が無い場合は何もしない。"""

        from app.utils.AnnictPlaybackSync import SyncAnnictHistoryPlaybackProgress

        user = MagicMock()
        user.annict_user_id = 1
        user.annict_access_token = 'encrypted'
        user.annict_auto_record_playback = True

        with patch('app.utils.AnnictPlaybackSync.SyncAnnictPlaybackProgress', AsyncMock()) as sync:
            await SyncAnnictHistoryPlaybackProgress(user, None)

        sync.assert_not_awaited()

    async def test_sync_failure_does_not_break_history_save(self) -> None:
        """外部投稿の失敗を握りつぶし、履歴保存の成功を保持する。"""

        from app.utils.AnnictPlaybackSync import SyncAnnictHistoryPlaybackProgress

        user = MagicMock()
        user.annict_user_id = 1
        user.annict_access_token = 'encrypted'
        user.annict_auto_record_playback = True
        progress = MagicMock(video_id=1)

        with patch(
            'app.utils.AnnictPlaybackSync.SyncAnnictPlaybackProgress',
            AsyncMock(side_effect=httpx.ConnectError('boom')),
        ):
            # 例外が外へ漏れないことを確認する
            await SyncAnnictHistoryPlaybackProgress(user, progress)


class SeriesMatcherParityTest(unittest.TestCase):
    """Bangumi から共通化した照合ロジックが同じ結果を返すことを検証する。"""

    def test_bangumi_client_delegates_to_shared_matcher(self) -> None:
        """BangumiClient の照合結果が SeriesMatcher と一致する。"""

        from app.utils.BangumiClient import BangumiClient

        subject = {'name': '作品A', 'name_cn': '作品A 中文'}
        self.assertEqual(
            BangumiClient._scoreSubjectTitle('作品A', subject),
            SeriesMatcher.scoreTitle('作品A', ['作品A', '作品A 中文']),
        )
        self.assertEqual(
            BangumiClient._normalizeSubjectTitle('作品A　4Kリマスター版'),
            SeriesMatcher.normalizeTitle('作品A　4Kリマスター版'),
        )

    def test_parse_episode_number_is_shared(self) -> None:
        """話数の解釈が共通化されている。"""

        from app.utils.BangumiClient import BangumiClient

        for value in ('12', '0', '1・2', '4.5', None):
            with self.subTest(value=value):
                self.assertEqual(
                    BangumiClient.parseEpisodeNumber(value),
                    SeriesMatcher.parseEpisodeNumber(value),
                )


class AnnictSeriesLinkTest(unittest.IsolatedAsyncioTestCase):
    """Annict 作品 ID が Series へ一意に保存されることを検証する。"""

    async def asyncSetUp(self) -> None:
        """
        テスト専用のメモリ内 SQLite を用意する。

        Returns:
            None
        """

        from typing import cast

        from tortoise import Tortoise

        from app.constants import DATABASE_CONFIG

        await Tortoise.init(
            db_url = 'sqlite://:memory:',
            modules = {'models': cast(list[str], DATABASE_CONFIG['apps']['models']['models'])},
        )
        await Tortoise.generate_schemas()

    async def asyncTearDown(self) -> None:
        """
        メモリ内 SQLite 接続を破棄する。

        Returns:
            None
        """

        from tortoise import Tortoise

        await Tortoise.close_connections()

    async def test_series_can_hold_both_bangumi_and_annict_ids(self) -> None:
        """1 つの Series が Bangumi と Annict の作品 ID を同時に保持できる。"""

        series = await Series.create(
            normalized_title='dual-linked',
            title='作品',
            description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
            bangumi_subject_id=1234,
            bangumi_subject_name='作品',
        )
        series.annict_work_id = 5678
        series.annict_work_name = '作品'
        await series.save(update_fields=['annict_work_id', 'annict_work_name'])

        reloaded = await Series.get(id=series.id)
        self.assertEqual(reloaded.bangumi_subject_id, 1234)
        self.assertEqual(reloaded.annict_work_id, 5678)

    async def test_annict_work_id_is_unique(self) -> None:
        """同じ Annict 作品 ID を複数の Series へ紐付けられない。"""

        from tortoise.exceptions import IntegrityError

        await Series.create(
            normalized_title='first', title='作品1', description='', genres=[],
            annict_work_id=999,
        )
        with self.assertRaises(IntegrityError):
            await Series.create(
                normalized_title='second', title='作品2', description='', genres=[],
                annict_work_id=999,
            )

    async def test_same_episode_is_not_recorded_twice(self) -> None:
        """同じエピソードを同じユーザーが二重に記録できない。"""

        from tortoise.exceptions import IntegrityError

        from app.models.AnnictEpisodeRecord import AnnictEpisodeRecord
        from app.models.User import User

        user = await User.create(name='annict-user', password='x', is_admin=False)
        await AnnictEpisodeRecord.create(user=user, annict_episode_id=501, annict_record_id=1)
        with self.assertRaises(IntegrityError):
            await AnnictEpisodeRecord.create(user=user, annict_episode_id=501, annict_record_id=2)
