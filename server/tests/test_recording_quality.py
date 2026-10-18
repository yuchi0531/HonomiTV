import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.utils.RecordingQuality import GetEDCBRecordingQuality, RecordingQuality


def BuildConfig(backend: str = 'EDCB', recorded_folders: list[str] | None = None) -> SimpleNamespace:
    """
    検証用の最小限のサーバー設定を組み立てる。

    Args:
        backend (str): 録画バックエンドの種類。
        recorded_folders (list[str] | None): 録画フォルダのパス一覧。

    Returns:
        SimpleNamespace: 検証用のサーバー設定。
    """

    return SimpleNamespace(
        general = SimpleNamespace(backend=backend),
        video = SimpleNamespace(recorded_folders=recorded_folders or ['/recorded']),
    )


class RecordingQualityTest(unittest.IsolatedAsyncioTestCase):
    """EDCB からの録画品質 (D/E/S) 取得を検証する。"""

    async def test_returns_none_for_non_edcb_backend(self) -> None:
        """EDCB 以外のバックエンドには品質統計が存在しないため取得しない。"""

        # EPGStation 構成では EDCB へ問い合わせない
        quality = await GetEDCBRecordingQuality('/recorded/foo.ts', BuildConfig(backend='EPGStation'))

        self.assertIsNone(quality)

    async def test_matches_recording_by_file_path(self) -> None:
        """録画済み一覧から同じファイルパスの品質統計を取り出す。"""

        edcb = AsyncMock()
        edcb.sendEnumRecInfoBasic.return_value = [
            {
                'id': 1,
                'rec_file_path': '/recorded/other.ts',
                'drops': 99,
                'scrambles': 99,
                'err_info': '',
            },
            {
                'id': 2,
                'rec_file_path': '/recorded/foo.ts',
                'drops': 12,
                'scrambles': 3,
                'err_info': '',
            },
        ]
        edcb.sendGetRecInfo.return_value = {'id': 2, 'drops': 12, 'scrambles': 3, 'err_info': '一部受信エラー'}

        with patch('app.utils.RecordingQuality.CtrlCmdUtil', return_value=edcb):
            quality = await GetEDCBRecordingQuality('/recorded/foo.ts', BuildConfig())

        self.assertIsNotNone(quality)
        assert quality is not None
        self.assertEqual(quality.drops, 12)
        self.assertEqual(quality.scrambles, 3)
        # err_info は一覧取得に含まれないため、詳細取得の値で補完される
        self.assertEqual(quality.error_info, '一部受信エラー')
        self.assertTrue(quality.has_problem)

    async def test_matches_windows_style_path_from_edcb(self) -> None:
        """EDCB が返すドライブレター付きパスでも録画フォルダ基準で突き合わせる。"""

        edcb = AsyncMock()
        edcb.sendEnumRecInfoBasic.return_value = [
            {'id': 1, 'rec_file_path': 'D:/TV-Record/foo.ts', 'drops': 2, 'scrambles': 0, 'err_info': ''},
        ]
        edcb.sendGetRecInfo.return_value = {'id': 1, 'drops': 2, 'scrambles': 0, 'err_info': ''}

        with patch('app.utils.RecordingQuality.CtrlCmdUtil', return_value=edcb):
            quality = await GetEDCBRecordingQuality('/recorded/foo.ts', BuildConfig())

        # パス表記が違っても同じ録画として扱う
        self.assertIsNotNone(quality)
        assert quality is not None
        self.assertEqual(quality.drops, 2)

    async def test_returns_none_when_recording_is_not_found(self) -> None:
        """一覧に該当する録画が無い場合は品質を返さない。"""

        edcb = AsyncMock()
        edcb.sendEnumRecInfoBasic.return_value = [
            {'id': 1, 'rec_file_path': '/recorded/other.ts', 'drops': 1, 'scrambles': 0, 'err_info': ''},
        ]

        with patch('app.utils.RecordingQuality.CtrlCmdUtil', return_value=edcb):
            self.assertIsNone(await GetEDCBRecordingQuality('/recorded/foo.ts', BuildConfig()))

    async def test_returns_none_when_edcb_rejects_the_request(self) -> None:
        """EDCB への問い合わせに失敗しても例外を投げず None を返す。"""

        edcb = AsyncMock()
        edcb.sendEnumRecInfoBasic.return_value = None

        with patch('app.utils.RecordingQuality.CtrlCmdUtil', return_value=edcb):
            self.assertIsNone(await GetEDCBRecordingQuality('/recorded/foo.ts', BuildConfig()))

    async def test_keeps_drop_and_scramble_when_detail_request_fails(self) -> None:
        """詳細取得に失敗しても、一覧から得たドロップとスクランブルは返す。"""

        edcb = AsyncMock()
        edcb.sendEnumRecInfoBasic.return_value = [
            {'id': 1, 'rec_file_path': '/recorded/foo.ts', 'drops': 7, 'scrambles': 1, 'err_info': ''},
        ]
        # 詳細取得は例外を投げる
        edcb.sendGetRecInfo.side_effect = RuntimeError('EDCB is busy')

        with patch('app.utils.RecordingQuality.CtrlCmdUtil', return_value=edcb):
            quality = await GetEDCBRecordingQuality('/recorded/foo.ts', BuildConfig())

        # 詳細取得の失敗は品質統計全体の失敗にしない
        self.assertIsNotNone(quality)
        assert quality is not None
        self.assertEqual(quality.drops, 7)
        self.assertEqual(quality.scrambles, 1)

    def test_error_count_counts_non_empty_lines(self) -> None:
        """EDCB の err_info は自由文なので、空でない行をエラー件数として数える。"""

        self.assertEqual(RecordingQuality(drops=0, scrambles=0, error_info='').error_count, 0)
        self.assertEqual(RecordingQuality(drops=0, scrambles=0, error_info='  \n \n').error_count, 0)
        self.assertEqual(RecordingQuality(drops=0, scrambles=0, error_info='1 行目').error_count, 1)
        # 複数行のエラーは行数分だけ数える
        self.assertEqual(
            RecordingQuality(drops=0, scrambles=0, error_info='1 行目\n2 行目\n\n3 行目').error_count,
            3,
        )
    async def test_clean_recording_reports_no_problem(self) -> None:
        """ドロップ・スクランブル・エラーが無い場合は has_problem が False になる。"""

        self.assertFalse(RecordingQuality(drops=0, scrambles=0, error_info='').has_problem)
        self.assertFalse(RecordingQuality(drops=0, scrambles=0, error_info='  ').has_problem)
        self.assertTrue(RecordingQuality(drops=1, scrambles=0, error_info='').has_problem)
        self.assertTrue(RecordingQuality(drops=0, scrambles=1, error_info='').has_problem)
        self.assertTrue(RecordingQuality(drops=0, scrambles=0, error_info='エラー').has_problem)
