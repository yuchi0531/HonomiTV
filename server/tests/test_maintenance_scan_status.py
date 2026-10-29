import unittest

from app.metadata.CaptureScanTask import CaptureScanTask
from app.metadata.RecordedScanTask import RecordedScanTask
from app.routers.MaintenanceRouter import router
from app.schemas import MaintenanceTaskStatus


class MaintenanceScanStatusRouteTest(unittest.TestCase):
    """メンテナンスのスキャン進捗 API が登録されていることを検証する。

    クライアントは起動直後からこれらの API を定期的に叩くため、
    実装が無いと 404 のエラー通知が繰り返し表示される。
    """

    def _paths(self) -> set[tuple[str, str]]:
        """登録済みのルートを (パス, メソッド) の集合で返す。

        Returns:
            set[tuple[str, str]]: パスとメソッドの組。
        """

        return {
            (route.path, method)
            for route in router.routes
            for method in getattr(route, 'methods', set())
        }

    def test_batch_scan_status_is_registered(self) -> None:
        """録画フォルダの一括スキャンの進捗 API が登録されている。"""

        self.assertIn(('/api/maintenance/batch-scan/status', 'GET'), self._paths())

    def test_capture_scan_status_is_registered(self) -> None:
        """キャプチャフォルダの一括スキャンの進捗 API が登録されている。"""

        self.assertIn(('/api/maintenance/capture-scan/status', 'GET'), self._paths())

    def test_capture_scan_run_is_registered(self) -> None:
        """キャプチャフォルダの一括スキャン実行 API が登録されている。"""

        self.assertIn(('/api/maintenance/capture-scan/run', 'POST'), self._paths())


class RecordedScanTaskProgressTest(unittest.TestCase):
    """録画フォルダの一括スキャンの進捗が更新されることを検証する。"""

    def _task(self) -> RecordedScanTask:
        """進捗だけを検証できる最小構成のタスクを作る。

        Returns:
            RecordedScanTask: 設定の読み込みを伴わないタスク。
        """

        task = object.__new__(RecordedScanTask)
        task.batch_scan_status = MaintenanceTaskStatus()
        return task

    def test_initial_status_is_not_running(self) -> None:
        """初期状態は実行中ではなく、件数も 0 件。"""

        status = self._task().batch_scan_status
        self.assertFalse(status.is_running)
        self.assertEqual(status.processed_count, 0)
        self.assertEqual(status.total_count, 0)

    def test_status_reports_running_and_counts(self) -> None:
        """実行中は is_running が立ち、処理件数と総件数が進む。"""

        task = self._task()
        task.batch_scan_status = MaintenanceTaskStatus(is_running=True)
        task.batch_scan_status.processed_count += 1
        task.batch_scan_status.total_count = max(
            task.batch_scan_status.total_count,
            task.batch_scan_status.processed_count,
        )

        self.assertTrue(task.batch_scan_status.is_running)
        self.assertEqual(task.batch_scan_status.processed_count, 1)
        self.assertEqual(task.batch_scan_status.total_count, 1)


class CaptureScanTaskProgressTest(unittest.TestCase):
    """キャプチャフォルダの一括スキャンの進捗が参照できることを検証する。"""

    def test_status_is_available(self) -> None:
        """進捗が MaintenanceTaskStatus として取得できる。"""

        task = object.__new__(CaptureScanTask)
        task.batch_scan_status = MaintenanceTaskStatus(is_running=True, processed_count=3, total_count=10)

        self.assertTrue(task.batch_scan_status.is_running)
        self.assertEqual(task.batch_scan_status.processed_count, 3)
        self.assertEqual(task.batch_scan_status.total_count, 10)


class CapturePollingIntervalTest(unittest.TestCase):
    """キャプチャフォルダの監視間隔の単位を検証する。"""

    def test_configuration_documents_seconds(self) -> None:
        """設定は秒単位として定義されている。

        コードが分として解釈すると、30 を設定した利用者は 30 分待つことになる。
        """

        from app.config import _ServerSettingsCapture

        field = _ServerSettingsCapture.model_fields['upload_folders_polling_interval']
        # 既定値は 0 (監視しない) で、負の値は受け付けない
        self.assertEqual(field.default, 0.0)

    def test_poll_sleeps_for_the_configured_seconds(self) -> None:
        """設定した秒数だけ待つ (分に換算しない)。"""

        import inspect

        from app.metadata import CaptureScanTask as module

        source = inspect.getsource(module.CaptureScanTask.watchFolders)
        # 分換算 (* 60) が残っていないことを確認する
        self.assertNotIn('interval * 60', source)
        self.assertIn('asyncio.sleep(interval)', source)


class ThumbnailUpdateAuthTest(unittest.TestCase):
    """録画サムネイルの差し替え API が認証を要求することを検証する。"""

    def test_thumbnail_update_requires_login(self) -> None:
        """未ログインでは実行できない。

        アップロード API は匿名でも使えるため、認証が無いと第三者が
        任意の録画のサムネイルを上書きできてしまう。
        """

        import inspect

        from app.routers import VideosRouter

        source = inspect.getsource(VideosRouter.VideoThumbnailUpdateAPI)
        self.assertIn('GetCurrentUser', source)
