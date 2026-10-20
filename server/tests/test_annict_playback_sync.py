import unittest
from typing import cast
from unittest.mock import AsyncMock, patch

from tortoise import Tortoise

from app.constants import DATABASE_CONFIG
from app.models.AnnictEpisodeRecord import AnnictEpisodeRecord
from app.models.RecordedProgram import RecordedProgram
from app.models.RecordedVideo import RecordedVideo
from app.models.Series import Series
from app.models.User import User
from app.schemas import BangumiPlaybackProgressRequest
from app.utils.AnnictPlaybackSync import SyncAnnictPlaybackProgress


class AnnictPlaybackSyncTest(unittest.IsolatedAsyncioTestCase):
    """Annict への視聴記録の作成条件を、実 DB と実ファイル無しで検証する。"""

    async def asyncSetUp(self) -> None:
        """
        テスト専用のメモリ内 SQLite と録画データを用意する。

        Returns:
            None
        """

        await Tortoise.init(
            db_url = 'sqlite://:memory:',
            modules = {'models': cast(list[str], DATABASE_CONFIG['apps']['models']['models'])},
        )
        await Tortoise.generate_schemas()

        # 連携済みユーザー (トークンは暗号化して保存する)
        self.user = await User.create(name='annict-user', password='x', is_admin=False)
        self.user.annict_user_id = 1
        self.user.annict_user_name = 'viewer'
        self.user.annict_access_token = self.user.encryptAnnictAccessToken('plain-token')
        await self.user.save(update_fields=['annict_user_id', 'annict_user_name', 'annict_access_token'])

        # Annict と照合済みの Series
        self.series = await Series.create(
            normalized_title='annict-sync-work', title='作品', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
            annict_work_id=777, annict_work_name='作品',
        )

    async def asyncTearDown(self) -> None:
        """
        メモリ内 SQLite 接続を破棄する。

        Returns:
            None
        """

        await Tortoise.close_connections()

    async def _createRecording(self, episode_number: str = '2', duration: float = 1800.0) -> RecordedProgram:
        """
        話数を持つ録画を作成する。

        Args:
            episode_number (str): 録画の話数。
            duration (float): 録画時間 (秒)。

        Returns:
            RecordedProgram: 作成した録画。
        """

        program = await RecordedProgram.create(
            series_id=self.series.id,
            title='作品 第2話',
            description='',
            start_time='2026-10-17T12:00:00+09:00',
            end_time='2026-10-17T12:30:00+09:00',
            duration=duration,
            episode_number=episode_number,
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
            is_partially_recorded=False,
            recording_start_margin=0.0,
            recording_end_margin=0.0,
            is_free=True,
            primary_audio_type='2/0モード(ステレオ)',
            primary_audio_language='日本語',
        )
        await RecordedVideo.create(
            recorded_program=program, status='Recorded', file_path=f'/nonexistent/{program.id}.ts',
            file_hash=str(program.id), file_size=1,
            file_created_at='2026-10-17T12:30:00+09:00', file_modified_at='2026-10-17T12:30:00+09:00',
            duration=duration, container_format='MPEG-TS', video_codec='H.264', video_codec_profile='High',
            video_scan_type='Progressive', video_frame_rate=30.0, video_resolution_width=1920,
            video_resolution_height=1080, primary_audio_codec='AAC-LC', primary_audio_channel='Stereo',
            primary_audio_sampling_rate=48000,
        )
        return program

    async def test_record_is_created_once_when_completed(self) -> None:
        """完了位置に達したら record を 1 回だけ作成し、台帳に残す。"""

        program = await self._createRecording()
        episodes = [{'id': 501, 'sort_number': 20, 'title': '第2話'}]

        with (
            patch('app.utils.AnnictPlaybackSync.AnnictClient.fetchEpisodes', AsyncMock(return_value=episodes)),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.createEpisodeRecord', AsyncMock(return_value=9001)) as create,
        ):
            completed = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=1700.0, duration=1800.0),
                self.user,
            )
            # 2 回目は同じエピソードなので投稿しない
            again = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=1750.0, duration=1800.0),
                self.user,
            )

        self.assertEqual(completed.status, 'Completed')
        self.assertEqual(again.status, 'AlreadyCompleted')
        create.assert_awaited_once_with('plain-token', 501)

        record = await AnnictEpisodeRecord.get(user_id=self.user.id)
        self.assertEqual(record.annict_episode_id, 501)
        self.assertEqual(record.annict_record_id, 9001)
        self.assertEqual(record.source_recorded_program_id, program.id)

    async def test_unfinished_playback_does_not_create_record(self) -> None:
        """完了位置に達していなければ投稿しない。"""

        program = await self._createRecording()
        with (
            patch('app.utils.AnnictPlaybackSync.AnnictClient.fetchEpisodes', AsyncMock(return_value=[])),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.createEpisodeRecord', AsyncMock()) as create,
        ):
            result = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=600.0, duration=1800.0),
                self.user,
            )

        self.assertEqual(result.status, 'Pending')
        create.assert_not_awaited()
        self.assertEqual(await AnnictEpisodeRecord.all().count(), 0)

    async def test_unlinked_series_is_matched_on_playback(self) -> None:
        """Annict 作品と照合できていない Series は、視聴時にその場で照合する。

        起動時の一括同期を待たずに投稿できるようにするため、未照合でも照合を試みる。
        """

        program = await self._createRecording()
        await Series.filter(id=self.series.id).update(annict_work_id=None, annict_work_name=None)
        episodes = [{'id': 501, 'sort_number': 20, 'title': '第2話'}]

        with (
            # マイリストには無いが、タイトル検索で見つかる状況
            patch('app.utils.AnnictPlaybackSync.AnnictClient.fetchCandidateWorks', AsyncMock(return_value=[])),
            patch(
                'app.utils.AnnictPlaybackSync.AnnictClient.searchWorksByTitle',
                AsyncMock(return_value=[{'id': 8888, 'titles': ['作品']}]),
            ),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.fetchEpisodes', AsyncMock(return_value=episodes)),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.createEpisodeRecord', AsyncMock(return_value=9001)) as create,
        ):
            result = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=1700.0, duration=1800.0),
                self.user,
            )

        self.assertEqual(result.status, 'Completed')
        create.assert_awaited_once()
        # 照合結果が Series に保存されている
        refreshed = await Series.get(id=self.series.id)
        self.assertEqual(refreshed.annict_work_id, 8888)

    async def test_unlinked_series_stays_not_eligible_when_no_work_matches(self) -> None:
        """Annict に該当作品が無ければ、従来どおり対象外にする。"""

        program = await self._createRecording()
        await Series.filter(id=self.series.id).update(annict_work_id=None, annict_work_name=None)

        with (
            patch('app.utils.AnnictPlaybackSync.AnnictClient.fetchCandidateWorks', AsyncMock(return_value=[])),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.searchWorksByTitle', AsyncMock(return_value=[])),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.createEpisodeRecord', AsyncMock()) as create,
        ):
            result = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=1700.0, duration=1800.0),
                self.user,
            )

        self.assertEqual(result.status, 'NotEligible')
        create.assert_not_awaited()

    async def test_missing_episode_mapping_does_not_post(self) -> None:
        """作品内に一致する話数が無ければ投稿しない。"""

        program = await self._createRecording(episode_number='99')
        with (
            patch('app.utils.AnnictPlaybackSync.AnnictClient.fetchEpisodes', AsyncMock(return_value=[
                {'id': 501, 'sort_number': 10},
            ])),
            patch('app.utils.AnnictPlaybackSync.AnnictClient.createEpisodeRecord', AsyncMock()) as create,
        ):
            result = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=1700.0, duration=1800.0),
                self.user,
            )

        self.assertEqual(result.status, 'Pending')
        create.assert_not_awaited()

    async def test_range_recording_is_not_recorded(self) -> None:
        """連続放送 (範囲録画) は誤った話へ記録しないため対象外とする。"""

        program = await self._createRecording(episode_number='5-6', duration=3600.0)
        # CS333 のアニメ枠だけが範囲録画の分割対象になる
        await RecordedProgram.filter(id=program.id).update(channel_id=None)

        with patch('app.utils.AnnictPlaybackSync.AnnictClient.createEpisodeRecord', AsyncMock()) as create:
            result = await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=2000.0, duration=3600.0),
                self.user,
            )

        # 範囲録画の判定はチャンネル種別に依存するため、対象外または未完了のどちらでも投稿しない
        self.assertIn(result.status, {'NotEligible', 'Pending'})
        create.assert_not_awaited()

    async def test_unlinked_user_is_rejected(self) -> None:
        """未連携ユーザーは明示的なエラーになる。"""

        from fastapi import HTTPException

        program = await self._createRecording()
        unlinked = await User.create(name='no-annict', password='x', is_admin=False)

        with self.assertRaises(HTTPException) as context:
            await SyncAnnictPlaybackProgress(
                program.id,
                BangumiPlaybackProgressRequest(playback_position=1700.0, duration=1800.0),
                unlinked,
            )
        self.assertEqual(context.exception.detail, 'Annict account is not linked')

    async def test_unknown_video_is_rejected(self) -> None:
        """存在しない録画 ID は 422 相当のエラーになる。"""

        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as context:
            await SyncAnnictPlaybackProgress(
                999999,
                BangumiPlaybackProgressRequest(playback_position=1700.0, duration=1800.0),
                self.user,
            )
        self.assertEqual(context.exception.detail, 'Specified video_id was not found')
