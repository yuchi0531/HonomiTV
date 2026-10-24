import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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



def BuildAsyncContextManager():
    """
    非同期コンテキストマネージャとして使えるモックを返す。

    Returns:
        object: async with で使えるモック。
    """

    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value = None)
    manager.__aexit__ = AsyncMock(return_value = False)
    return manager


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
            # 実 DB を使わないため、スキーマ変換は通すだけにする
            patch(
                'app.metadata.RecordedScanTask.ThumbnailGenerator.fromRecordedProgram',
                return_value = SimpleNamespace(generateAndSave = generate),
            ),
            patch('app.metadata.RecordedScanTask.ProcessLimiter.getSemaphore', return_value = BuildAsyncContextManager()),
            patch('app.metadata.RecordedScanTask.DriveIOLimiter.getSemaphore', AsyncMock(return_value = BuildAsyncContextManager())),
        ):
            await self.scan_task._RecordedScanTask__regenerateThumbnailOnly(program)

        # サムネイル生成が 1 回だけ呼ばれる
        generate.assert_awaited_once()
        # 完了後はバックグラウンドタスクの管理から外れる
        self.assertEqual(len(self.scan_task._background_tasks), 0)

    async def test_missing_thumbnail_is_regenerated_on_scan(self) -> None:
        """実ファイルが失われている録画を、起動時に生成し直す。

        外部でのエンコード置換や生成失敗でサムネイルだけ失われることがあり、
        そのままでは一覧のサムネイルが空のまま残ってしまう。
        """

        video_row = {'id': 1, 'file_hash': 'deadbeef', 'file_path': '/recorded/encoded.ts'}
        recorded_program = SimpleNamespace(
            recorded_video = SimpleNamespace(file_path = '/recorded/encoded.ts'),
        )
        generate = AsyncMock()

        with (
            patch(
                'app.metadata.RecordedScanTask.RecordedVideo.filter',
                return_value = SimpleNamespace(values = AsyncMock(return_value = [video_row])),
            ),
            patch(
                'app.metadata.RecordedScanTask.RecordedProgram.filter',
                return_value = SimpleNamespace(
                    prefetch_related = MagicMock(return_value = SimpleNamespace(
                        get_or_none = AsyncMock(return_value = recorded_program),
                    )),
                ),
            ),
            # サムネイルは存在しない
            patch.object(self.scan_task, '_RecordedScanTask__isThumbnailFileExists', AsyncMock(return_value = False)),
            # 録画ファイル自体は存在する
            patch('app.metadata.RecordedScanTask.anyio.Path.is_file', AsyncMock(return_value = True)),
            # 実 DB を使わないため、スキーマ変換は通すだけにする
            patch('app.metadata.RecordedScanTask.schemas.RecordedProgram.model_validate', return_value = recorded_program),
            patch(
                'app.metadata.RecordedScanTask.ThumbnailGenerator.fromRecordedProgram',
                return_value = SimpleNamespace(generateAndSave = generate),
            ),
            patch('app.metadata.RecordedScanTask.ProcessLimiter.getSemaphore', return_value = BuildAsyncContextManager()),
            patch('app.metadata.RecordedScanTask.DriveIOLimiter.getSemaphore', AsyncMock(return_value = BuildAsyncContextManager())),
        ):
            await self.scan_task._RecordedScanTask__regenerateMissingThumbnails()

        generate.assert_awaited_once()

    async def test_existing_thumbnail_is_not_regenerated(self) -> None:
        """サムネイルが既にある録画は生成し直さない。"""

        video_row = {'id': 1, 'file_hash': 'exists', 'file_path': '/recorded/ok.ts'}
        generate = AsyncMock()

        with (
            patch(
                'app.metadata.RecordedScanTask.RecordedVideo.filter',
                return_value = SimpleNamespace(values = AsyncMock(return_value = [video_row])),
            ),
            # サムネイルが存在する
            patch.object(self.scan_task, '_RecordedScanTask__isThumbnailFileExists', AsyncMock(return_value = True)),
            patch(
                'app.metadata.RecordedScanTask.ThumbnailGenerator.fromRecordedProgram',
                return_value = SimpleNamespace(generateAndSave = generate),
            ),
        ):
            await self.scan_task._RecordedScanTask__regenerateMissingThumbnails()

        generate.assert_not_awaited()
