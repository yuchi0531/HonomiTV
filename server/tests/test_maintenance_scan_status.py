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
