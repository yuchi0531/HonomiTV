from __future__ import annotations

import json
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import patch

import anyio
import httpx

from app.config import ServerSettingsNotificationService, WatchUrlConfig
from app.constants import JST
from app.schemas import RecordedProgram
from app.utils.NotificationService import (
    NotificationManager,
    TelegramNotificationService,
    WebhookNotificationService,
)


def BuildRecordedProgram(**overrides: Any) -> RecordedProgram:
    """
    通知の検証に必要な最小限の録画番組情報を組み立てる。

    Args:
        **overrides (Any): 既定値から差し替えるフィールド。

    Returns:
        RecordedProgram: 検証用の録画番組情報。
    """

    program: dict[str, Any] = {
        'id': 42,
        'recorded_video': {
            'status': 'Recorded',
            'file_path': '/nonexistent/recorded.ts',
            'file_hash': 'hash',
            'file_size': 1024,
            'file_created_at': datetime(2026, 10, 17, 12, 0, tzinfo=JST),
            'file_modified_at': datetime(2026, 10, 17, 12, 30, tzinfo=JST),
            'recording_start_time': datetime(2026, 10, 17, 12, 0, tzinfo=JST),
            'recording_end_time': datetime(2026, 10, 17, 12, 30, tzinfo=JST),
            'duration': 1800.0,
            'container_format': 'MPEG-TS',
            'video_codec': 'H.264',
            'video_codec_profile': 'High',
            'video_scan_type': 'Progressive',
            'video_frame_rate': 30.0,
            'video_resolution_width': 1920,
            'video_resolution_height': 1080,
            'primary_audio_codec': 'AAC-LC',
            'primary_audio_channel': 'Stereo',
            'primary_audio_sampling_rate': 48000,
            'created_at': datetime(2026, 10, 17, 12, 30, tzinfo=JST),
            'updated_at': datetime(2026, 10, 17, 12, 30, tzinfo=JST),
        },
        'channel': {
            'id': 'NID32736-SID1024',
            'display_channel_id': 'gr011',
            'network_id': 32736,
            'service_id': 1024,
            'transport_stream_id': 32736,
            'remocon_id': 1,
            'channel_number': '011',
            'type': 'GR',
            'name': 'テスト放送',
        },
        'title': 'テストニュース',
        'description': '番組の概要です。',
        'start_time': datetime(2026, 10, 17, 12, 0, tzinfo=JST),
        'end_time': datetime(2026, 10, 17, 13, 0, tzinfo=JST),
        'duration': 3600.0,
        'created_at': datetime(2026, 10, 17, 13, 0, tzinfo=JST),
        'updated_at': datetime(2026, 10, 17, 13, 0, tzinfo=JST),
    }
    program.update(overrides)
    return RecordedProgram.model_validate(program)


class RecordingHTTPClient:
    """httpx.AsyncClient の代わりに送信内容だけを記録するテスト用クライアント。"""

    # 直近のリクエスト内容
    requests: list[dict[str, Any]] = []
    # 次のリクエストで発生させる HTTP ステータスコード
    status_code: int = 204

    def __init__(self, *_: Any, **__: Any) -> None:
        """
        テスト用クライアントを初期化する。

        Args:
            *_ (Any): 実際の httpx.AsyncClient の引数。
            **__ (Any): 実際の httpx.AsyncClient のキーワード引数。
        """

    async def __aenter__(self) -> RecordingHTTPClient:
        """
        コンテキストマネージャーとして自身を返す。

        Returns:
            RecordingHTTPClient: 自身。
        """

        return self

    async def __aexit__(self, *_: Any) -> None:
        """
        コンテキストマネージャーを抜ける。

        Args:
            *_ (Any): 例外情報。

        Returns:
            None
        """

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """
        リクエスト内容を記録し、設定済みのステータスコードを返す。

        Args:
            url (str): リクエスト先。
            **kwargs (Any): json / data / files / timeout など。

        Returns:
            httpx.Response: 設定済みステータスコードのレスポンス。
        """

        RecordingHTTPClient.requests.append({'url': url, **kwargs})
        return httpx.Response(
            status_code = RecordingHTTPClient.status_code,
            request = httpx.Request('POST', url),
        )


class WebhookNotificationServiceTest(unittest.IsolatedAsyncioTestCase):
    """Discord 互換の Webhook 通知を検証する。"""

    async def asyncSetUp(self) -> None:
        """
        各テストの前にリクエスト記録を初期化する。

        Returns:
            None
        """

        RecordingHTTPClient.requests = []
        RecordingHTTPClient.status_code = 204
        self.patcher = patch(
            'app.utils.NotificationService.httpx.AsyncClient',
            RecordingHTTPClient,
        )
        self.patcher.start()

    async def asyncTearDown(self) -> None:
        """
        差し替えた HTTP クライアントを元に戻す。

        Returns:
            None
        """

        self.patcher.stop()

    def _config(self, **overrides: Any) -> ServerSettingsNotificationService:
        """
        検証用の通知サービス設定を組み立てる。

        Args:
            **overrides (Any): 既定値から差し替えるフィールド。

        Returns:
            ServerSettingsNotificationService: 検証用の通知サービス設定。
        """

        values: dict[str, Any] = {
            'type': 'Webhook',
            'enabled': True,
            'webhook_url': 'https://discord.com/api/webhooks/1234/token',
            'watch_urls': [],
        }
        values.update(overrides)
        return ServerSettingsNotificationService(**values)

    async def test_sends_discord_embed_with_program_fields(self) -> None:
        """番組情報が Discord の Embed として送信される。"""

        service = WebhookNotificationService(self._config())

        await service.send_new_recording(BuildRecordedProgram())

        self.assertEqual(len(RecordingHTTPClient.requests), 1)
        request = RecordingHTTPClient.requests[0]
        self.assertEqual(request['url'], 'https://discord.com/api/webhooks/1234/token')
        # サムネイルが無い場合は JSON で送る
        payload = request['json']
        self.assertNotIn('content', payload)
        # メンションを発生させない
        self.assertEqual(payload['allowed_mentions'], {'parse': []})

        embed = payload['embeds'][0]
        self.assertEqual(embed['title'], '📺 新しい録画を検出しました')
        self.assertEqual(embed['color'], 0xE64F97)
        self.assertEqual(embed['footer'], {'text': 'KonomiTV'})
        self.assertIn('テストニュース', embed['description'])
        self.assertIn('番組の概要です。', embed['description'])

        # チャンネル・放送時間・長さがフィールドとして並ぶ
        fields = {field['name']: field['value'] for field in embed['fields']}
        self.assertEqual(fields['チャンネル'], 'テスト放送')
        self.assertEqual(fields['放送時間'], '2026/10/17 12:00 - 13:00')
        self.assertEqual(fields['長さ'], '1時間0分')

    async def test_uses_watch_links_only_when_configured(self) -> None:
        """視聴リンクは設定時のみ、録画 ID を含む Markdown リンクとして追加される。"""

        service = WebhookNotificationService(self._config(watch_urls=[
            WatchUrlConfig(text='🏠 ローカルで視聴', base_url='https://internal.example.com'),
            WatchUrlConfig(text='🌐 外部から視聴', base_url='https://external.example.com'),
        ]))

        await service.send_new_recording(BuildRecordedProgram())

        fields = RecordingHTTPClient.requests[0]['json']['embeds'][0]['fields']
        links = {field['name']: field['value'] for field in fields if field['inline'] is True}
        self.assertEqual(links['🏠 ローカルで視聴'], '[視聴する](https://internal.example.com/videos/watch/42)')
        self.assertEqual(links['🌐 外部から視聴'], '[視聴する](https://external.example.com/videos/watch/42)')

    async def test_skips_watch_links_when_recording_id_is_unknown(self) -> None:
        """録画 ID が未確定なら視聴リンクを生成しない (開けないリンクを通知しない)。"""

        service = WebhookNotificationService(self._config(watch_urls=[
            WatchUrlConfig(text='🏠 ローカルで視聴', base_url='https://internal.example.com'),
        ]))

        await service.send_new_recording(BuildRecordedProgram(id=-1))

        fields = RecordingHTTPClient.requests[0]['json']['embeds'][0]['fields']
        self.assertEqual([field['name'] for field in fields], ['チャンネル', '放送時間', '長さ'])

    async def test_truncates_long_description_to_discord_limit(self) -> None:
        """Discord の Embed 上限を超える本文は上限ちょうどまで切り詰める。"""

        service = WebhookNotificationService(self._config())

        await service.send_new_recording(BuildRecordedProgram(description='あ' * 5000))

        description = RecordingHTTPClient.requests[0]['json']['embeds'][0]['description']
        self.assertLessEqual(len(description), WebhookNotificationService.EMBED_DESCRIPTION_MAX_LENGTH)
        self.assertTrue(description.endswith('...'))

    async def test_truncates_long_title_and_channel_name(self) -> None:
        """番組名・チャンネル名が長くても個々の上限に収める。"""

        service = WebhookNotificationService(self._config())

        await service.send_new_recording(
            BuildRecordedProgram(title='長' * 500, channel={
                'id': 'NID32736-SID1024', 'display_channel_id': 'gr011',
                'network_id': 32736, 'service_id': 1024, 'transport_stream_id': 32736,
                'remocon_id': 1, 'channel_number': '011', 'type': 'GR', 'name': '局' * 2000,
            }),
        )

        embed = RecordingHTTPClient.requests[0]['json']['embeds'][0]
        self.assertLessEqual(len(embed['description']), WebhookNotificationService.EMBED_DESCRIPTION_MAX_LENGTH)
        channel_field = next(field for field in embed['fields'] if field['name'] == 'チャンネル')
        self.assertLessEqual(
            len(channel_field['value']),
            WebhookNotificationService.EMBED_FIELD_VALUE_MAX_LENGTH,
        )

    async def test_limits_field_count_and_total_length(self) -> None:
        """視聴リンクが多すぎる場合は、フィールド数と合計文字数の上限に収まるよう間引く。"""

        # 上限を超える数の視聴リンクを設定する
        watch_urls = [
            WatchUrlConfig(text=f'リンク {index}', base_url=f'https://example{index}.test')
            for index in range(40)
        ]
        service = WebhookNotificationService(self._config(watch_urls=watch_urls))

        await service.send_new_recording(BuildRecordedProgram(description='あ' * 1000))

        embed = RecordingHTTPClient.requests[0]['json']['embeds'][0]
        self.assertLessEqual(len(embed['fields']), WebhookNotificationService.EMBED_FIELD_MAX_COUNT)
        total_length = len(embed['title']) + len(embed['description']) + sum(
            len(field['name']) + len(field['value']) for field in embed['fields']
        )
        self.assertLessEqual(total_length, WebhookNotificationService.EMBED_TOTAL_MAX_LENGTH)
        # 通知の要である基本フィールドは残る
        names = [field['name'] for field in embed['fields']]
        self.assertEqual(names[:3], ['チャンネル', '放送時間', '長さ'])

    async def test_empty_description_still_produces_valid_embed(self) -> None:
        """番組概要が空でも本文には番組名が残り、通知が壊れない。"""

        service = WebhookNotificationService(self._config())

        await service.send_new_recording(BuildRecordedProgram(description=''))

        description = RecordingHTTPClient.requests[0]['json']['embeds'][0]['description']
        self.assertIn('テストニュース', description)

    async def test_attaches_thumbnail_as_multipart_when_available(self) -> None:
        """サムネイルがある場合は multipart/form-data で添付し、Embed の画像に紐付ける。"""

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            thumbnail_path = Path(temp_dir) / 'thumbnail.webp'
            thumbnail_path.write_bytes(b'RIFFxxxxWEBP')

            service = WebhookNotificationService(self._config())
            await service.send_new_recording(BuildRecordedProgram(), anyio.Path(thumbnail_path))

        request = RecordingHTTPClient.requests[0]
        # 添付を送る場合は JSON ではなく payload_json に入れる
        self.assertNotIn('json', request)
        payload = json.loads(request['data']['payload_json'])
        self.assertEqual(payload['embeds'][0]['image'], {'url': 'attachment://thumbnail.webp'})
        self.assertEqual(payload['attachments'], [{'id': 0, 'filename': 'thumbnail.webp'}])
        self.assertEqual(request['files']['files[0]'][0], 'thumbnail.webp')
        self.assertEqual(request['files']['files[0]'][2], 'image/webp')

    async def test_falls_back_to_json_when_thumbnail_is_missing(self) -> None:
        """サムネイルが存在しなくても、テキスト通知としては送信できる。"""

        service = WebhookNotificationService(self._config())

        await service.send_new_recording(
            BuildRecordedProgram(),
            anyio.Path('/nonexistent/thumbnail.webp'),
        )

        request = RecordingHTTPClient.requests[0]
        self.assertIn('json', request)
        self.assertNotIn('image', request['json']['embeds'][0])

    async def test_test_notification_marks_itself_as_test(self) -> None:
        """テスト通知はタイトルでテストであることを明示し、サムネイルは添付しない。"""

        service = WebhookNotificationService(self._config())

        await service.send_test(BuildRecordedProgram())

        request = RecordingHTTPClient.requests[0]
        self.assertEqual(request['json']['embeds'][0]['title'], '🔔 通知設定テスト')
        self.assertNotIn('image', request['json']['embeds'][0])

    async def test_raises_when_webhook_url_is_blank(self) -> None:
        """Webhook URL が空の場合は送信せずに失敗する。"""

        service = WebhookNotificationService(self._config(webhook_url='   '))

        with self.assertRaises(ValueError):
            await service.send_new_recording(BuildRecordedProgram())
        self.assertEqual(RecordingHTTPClient.requests, [])

    async def test_propagates_http_error(self) -> None:
        """Webhook がエラーを返した場合は例外として伝播する。"""

        RecordingHTTPClient.status_code = 400
        service = WebhookNotificationService(self._config())

        with self.assertRaises(httpx.HTTPStatusError):
            await service.send_new_recording(BuildRecordedProgram())

    async def test_unknown_channel_falls_back_to_placeholder(self) -> None:
        """チャンネル情報が無い録画でも通知できる。"""

        service = WebhookNotificationService(self._config())

        await service.send_new_recording(BuildRecordedProgram(channel=None))

        fields = RecordingHTTPClient.requests[0]['json']['embeds'][0]['fields']
        channel_field = next(field for field in fields if field['name'] == 'チャンネル')
        self.assertEqual(channel_field['value'], '不明なチャンネル')


class NotificationManagerTest(unittest.IsolatedAsyncioTestCase):
    """通知サービスの組み立てと並列送信を検証する。"""

    async def asyncSetUp(self) -> None:
        """
        各テストの前にリクエスト記録を初期化する。

        Returns:
            None
        """

        RecordingHTTPClient.requests = []
        RecordingHTTPClient.status_code = 204
        self.patcher = patch(
            'app.utils.NotificationService.httpx.AsyncClient',
            RecordingHTTPClient,
        )
        self.patcher.start()

    async def asyncTearDown(self) -> None:
        """
        差し替えた HTTP クライアントを元に戻す。

        Returns:
            None
        """

        self.patcher.stop()

    async def test_builds_webhook_service_only_when_enabled_and_configured(self) -> None:
        """有効かつ URL が設定されている Webhook だけをサービスとして採用する。"""

        manager = NotificationManager([
            ServerSettingsNotificationService(type='Webhook', enabled=True, webhook_url='https://example.test/hook'),
            # 無効なものは対象外
            ServerSettingsNotificationService(type='Webhook', enabled=False, webhook_url='https://example.test/hook2'),
            # URL 未設定のものは対象外
            ServerSettingsNotificationService(type='Webhook', enabled=True, webhook_url=''),
        ])

        self.assertEqual(len(manager.services), 1)
        self.assertIsInstance(manager.services[0], WebhookNotificationService)

    async def test_keeps_telegram_support(self) -> None:
        """既存の Telegram 通知も引き続き組み立てられる。"""

        manager = NotificationManager([
            ServerSettingsNotificationService(type='Telegram', enabled=True, bot_token='token', chat_id='123'),
        ])

        self.assertEqual(len(manager.services), 1)
        self.assertIsInstance(manager.services[0], TelegramNotificationService)

    async def test_continues_after_a_service_fails(self) -> None:
        """1 つのサービスが失敗しても、他のサービスへの送信は継続する。"""

        # Telegram は 400 を返し、Webhook は成功する状況を作る
        original_post = RecordingHTTPClient.post
        call_count = {'value': 0}

        async def post(self_client: RecordingHTTPClient, url: str, **kwargs: Any) -> httpx.Response:
            """
            最初の呼び出しだけ失敗させ、以降は成功させる。

            Args:
                self_client (RecordingHTTPClient): 呼び出し元。
                url (str): リクエスト先。
                **kwargs (Any): リクエストオプション。

            Returns:
                httpx.Response: ステータスコード付きのレスポンス。
            """

            call_count['value'] += 1
            status_code = 400 if call_count['value'] == 1 else 204
            RecordingHTTPClient.requests.append({'url': url, **kwargs})
            return httpx.Response(status_code=status_code, request=httpx.Request('POST', url))

        with unittest.mock.patch.object(RecordingHTTPClient, 'post', post):
            manager = NotificationManager([
                ServerSettingsNotificationService(type='Webhook', enabled=True, webhook_url='https://example.test/a'),
                ServerSettingsNotificationService(type='Webhook', enabled=True, webhook_url='https://example.test/b'),
            ])
            # send_new_recording は例外を握りつぶしてログに出すだけなので、呼び出しが完了することを確認する
            await manager.send_new_recording(BuildRecordedProgram())

        # 2 サービスとも送信が試行されている
        self.assertEqual(len(RecordingHTTPClient.requests), 2)
        self.assertEqual(original_post, RecordingHTTPClient.post)

    async def test_test_notification_raises_first_error(self) -> None:
        """テスト通知では失敗を握りつぶさず、呼び出し元へエラーを返す。"""

        RecordingHTTPClient.status_code = 400
        manager = NotificationManager([
            ServerSettingsNotificationService(type='Webhook', enabled=True, webhook_url='https://example.test/a'),
        ])

        with self.assertRaises(httpx.HTTPStatusError):
            await manager.send_test(BuildRecordedProgram())

    async def test_test_notification_without_services_fails(self) -> None:
        """有効な通知サービスが無い場合、テスト通知は明示的に失敗する。"""

        manager = NotificationManager([
            ServerSettingsNotificationService(type='Webhook', enabled=False, webhook_url='https://example.test/a'),
        ])

        with self.assertRaises(Exception):
            await manager.send_test(BuildRecordedProgram())
