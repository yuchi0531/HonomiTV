import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.metadata.RecordedScanTask import RecordedScanTask


class RecordedScanTaskLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """ローカル録画監視と録画バックエンド同期のライフサイクル分離を検証する。"""

    async def asyncSetUp(self) -> None:
        """各テストでシングルトンのタスク状態を初期化する。"""

        RecordedScanTask._RecordedScanTask__instance = None  # type: ignore[attr-defined]
        minimal_config = SimpleNamespace(
            general = SimpleNamespace(backend='EPGStation'),
            video = SimpleNamespace(recorded_folders=[]),
        )
        with patch('app.metadata.RecordedScanTask.Config', return_value=minimal_config):
            self.scan_task = RecordedScanTask()


    async def asyncTearDown(self) -> None:
        """テスト終了時に生成したバックグラウンドタスクを停止する。"""

        await self.scan_task.stop()
        RecordedScanTask._RecordedScanTask__instance = None  # type: ignore[attr-defined]


    async def test_backend_sync_does_not_start_local_folder_scan_or_watch(self) -> None:
        """EDCB / EPGStation 用同期がローカル全件スキャンと変更監視を起動しないことを検証する。"""

        scan_task = self.scan_task
        with (
            patch.object(scan_task, '_RecordedScanTask__syncActiveRecordingFiles', new=AsyncMock()),
            patch.object(scan_task, '_RecordedScanTask__syncEPGStationRecentRecordedFiles', new=AsyncMock()),
            patch.object(scan_task, 'runBatchScan', new=AsyncMock()) as run_batch_scan,
            patch.object(scan_task, 'watchRecordedFolders', new=AsyncMock()) as watch_recorded_folders,
        ):
            await scan_task.startBackendRecordingSync()
            await asyncio.sleep(0)
            await scan_task.stopBackendRecordingSync()

        run_batch_scan.assert_not_awaited()
        watch_recorded_folders.assert_not_awaited()


    async def test_local_monitor_does_not_start_backend_sync(self) -> None:
        """Mirakurun 用ローカル監視が録画バックエンド同期を暗黙に起動しないことを検証する。"""

        scan_task = self.scan_task
        with (
            patch.object(scan_task, 'runBatchScan', new=AsyncMock()),
            patch.object(scan_task, 'watchRecordedFolders', new=AsyncMock()),
            patch.object(scan_task, 'startBackendRecordingSync', new=AsyncMock()) as start_backend_sync,
        ):
            await scan_task.start()
            await asyncio.sleep(0)
            await scan_task.stop()

        start_backend_sync.assert_not_awaited()


class ThumbnailRegenerationTest(unittest.IsolatedAsyncioTestCase):
    """ハッシュが変わったときにサムネイルが生成し直されることを検証する。"""

    async def asyncSetUp(self) -> None:
        """検証用のタスクを初期化する。"""

        RecordedScanTask._RecordedScanTask__instance = None  # type: ignore[attr-defined]
        minimal_config = SimpleNamespace(
            general = SimpleNamespace(backend='EDCB'),
            video = SimpleNamespace(recorded_folders=[]),
        )
        with patch('app.metadata.RecordedScanTask.Config', return_value=minimal_config):
            self.scan_task = RecordedScanTask()

    async def asyncTearDown(self) -> None:
        """後始末する。"""

        await self.scan_task.stop()
        RecordedScanTask._RecordedScanTask__instance = None  # type: ignore[attr-defined]

    async def test_regenerates_thumbnail_when_previous_one_is_missing(self) -> None:
        """旧ハッシュのサムネイルが無い場合は、サムネイルだけを生成し直す。

        外部でのエンコード置換によりファイルのハッシュが変わると、旧サムネイルを
        リネームできず、サムネイルが空のまま残ってしまう。
        """

        program = SimpleNamespace(
            recorded_video = SimpleNamespace(file_path='/recorded/replaced.ts'),
        )
        generate = AsyncMock()

        with (
            patch('app.metadata.RecordedScanTask.THUMBNAILS_DIR', '/nonexistent/thumbnails'),
            patch(
                'app.metadata.RecordedScanTask.ThumbnailGenerator.fromRecordedProgram',
                return_value = SimpleNamespace(generateAndSave = generate),
            ),
            patch('app.metadata.RecordedScanTask.ProcessLimiter.getSemaphore', AsyncMock()),
            patch('app.metadata.RecordedScanTask.DriveIOLimiter.getSemaphore', AsyncMock()),
        ):
            await self.scan_task._RecordedScanTask__regenerateThumbnailOnly(program)

        # サムネイル生成が 1 回だけ呼ばれる
        generate.assert_awaited_once()
        # 完了後はバックグラウンドタスクの管理から外れる
        self.assertEqual(len(self.scan_task._background_tasks), 0)
