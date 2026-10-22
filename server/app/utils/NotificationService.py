from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

import anyio
import httpx

from app import logging, schemas
from app.config import NotificationEventType, ServerSettingsNotificationService
from app.utils.RecordingQuality import RecordingQuality


class NotificationEvent:
    """
    通知するイベントを表すクラス。

    どの通知先にも同じ内容を送るため、サービス側はこのクラスを受け取って
    自分たちの形式へ整形するだけで済む。
    """

    # イベントの種類
    type: NotificationEventType
    # 録画イベントの対象 (予約イベントでは None)
    recorded_program: schemas.RecordedProgram | None
    # 予約イベントの対象 (録画イベントでは None)
    reservation: schemas.Reservation | None
    # 録画品質の統計 (EDCB からのみ取得できる。取得できない場合は None)
    recording_quality: RecordingQuality | None

    def __init__(
        self,
        type: NotificationEventType,
        recorded_program: schemas.RecordedProgram | None = None,
        reservation: schemas.Reservation | None = None,
        recording_quality: RecordingQuality | None = None,
    ):
        """
        通知イベントを初期化する。

        Args:
            type (NotificationEventType): イベントの種類。
            recorded_program (schemas.RecordedProgram | None): 録画イベントの対象。
            reservation (schemas.Reservation | None): 予約イベントの対象。
            recording_quality (RecordingQuality | None): 録画品質の統計。
        """

        self.type = type
        self.recorded_program = recorded_program
        self.reservation = reservation
        self.recording_quality = recording_quality

    def GetQualitySummary(self) -> str | None:
        """
        録画品質を 1 行の要約文字列にする。

        通知先ごとに書式が異なるため、本文へ埋め込むための共通表現をここで組み立てる。
        D / E / S はそれぞれドロップ数 / エラー数 / スクランブル数を表す。

        Returns:
            str | None: 品質の要約。品質情報が無い場合は None。
        """

        if self.recording_quality is None:
            return None
        quality = self.recording_quality
        # D / E / S を並べれば状態が一目で分かるため、問題の有無にかかわらず同じ書式で出す
        return f'📊録画品質 D {quality.drops} / E {quality.error_count} / S {quality.scrambles}'


class NotificationService(ABC):
    """
    通知サービスの抽象基底クラス
    """

    def __init__(self, config: ServerSettingsNotificationService):
        self.config = config

    def isEventEnabled(self, event_type: NotificationEventType) -> bool:
        """
        指定されたイベントをこの通知先へ送るかどうかを返す。

        Args:
            event_type (NotificationEventType): 判定するイベントの種類。

        Returns:
            bool: 送信する場合は True。
        """

        return event_type in self.config.events

    @abstractmethod
    async def send_event(
        self,
        event: NotificationEvent,
        thumbnail_path: anyio.Path | None = None,
    ) -> None:
        """
        イベント通知を送信する

        Args:
            event (NotificationEvent): 送信するイベント。
            thumbnail_path (anyio.Path | None): サムネイル画像のパス（存在する場合）。
        """
        pass

    @abstractmethod
    async def send_test(self, recorded_program: schemas.RecordedProgram) -> None:
        """
        テスト通知を送信する

        Args:
            recorded_program: テスト用の録画番組情報
        """
        pass


class TelegramNotificationService(NotificationService):
    """
    Telegram Bot API を使用した通知サービス
    """

    def __init__(self, config: ServerSettingsNotificationService):
        super().__init__(config)
        self.bot_token = config.bot_token
        self.chat_id = config.chat_id
        self.base_url = f'https://api.telegram.org/bot{self.bot_token}'

    async def send_event(
        self,
        event: NotificationEvent,
        thumbnail_path: anyio.Path | None = None,
    ) -> None:
        """イベント通知を送信"""

        # この通知先が受け取らないイベントは何もしない
        if self.isEventEnabled(event.type) is False:
            return

        # メッセージテキストを構築
        message = self._build_event_message(event)

        try:
            # サムネイルを添付できるのは録画イベントだけ
            recorded_program = event.recorded_program
            if recorded_program is not None and thumbnail_path is not None and await thumbnail_path.exists():
                # サムネイル付きで送信
                await self._send_photo_with_caption(message, thumbnail_path, recorded_program)
            else:
                # テキストのみ送信
                await self._send_text_message(message, recorded_program)
        except Exception as ex:
            logging.warning(f'Telegram通知の送信に失敗しました: {ex}')
            raise


    def _build_event_message(self, event: NotificationEvent) -> str:
        """
        イベント種別に応じたメッセージ本文を構築する

        Args:
            event (NotificationEvent): 送信するイベント。

        Returns:
            str: Telegram へ送る本文。
        """

        if event.type == 'RecordingStarted':
            assert event.recorded_program is not None
            # 録画開始時点では品質統計がまだ無いため、品質行は付けない
            return self._build_recording_message(
                event.recorded_program,
                heading = '🔴 **録画を開始しました**',
            )
        if event.type == 'RecordingCompleted':
            assert event.recorded_program is not None
            # 「検出」では録画開始と区別が付かないため、録画が終わったことを明示する
            return self._build_recording_message(
                event.recorded_program,
                heading = '✅ **録画が完了しました**',
                quality_summary = event.GetQualitySummary(),
            )
        if event.type == 'FileDetected':
            assert event.recorded_program is not None
            # 新たにファイルが見つかったことだけを伝える (録画完了とは別のイベント)
            return self._build_recording_message(
                event.recorded_program,
                heading = '📁 **新しいファイルを検出しました**',
            )
        if event.type == 'FileDeleted':
            assert event.recorded_program is not None
            return self._build_recording_message(
                event.recorded_program,
                heading = '🗑 **録画ファイルが削除されました**',
            )
        if event.type == 'EncodeCompleted':
            assert event.encode_info is not None
            return self._build_encode_message(event.encode_info)
        assert event.reservation is not None
        if event.type == 'ReservationAdded':
            return self._build_reservation_message(event.reservation, heading = '🗓 **録画予約を追加しました**')
        return self._build_reservation_message(event.reservation, heading = '🗑 **録画予約を削除しました**')


    def _build_reservation_message(self, reservation: schemas.Reservation, heading: str) -> str:
        """
        予約情報からメッセージ本文を構築する

        Args:
            reservation (schemas.Reservation): 予約情報。
            heading (str): 先頭に付ける見出し。

        Returns:
            str: Telegram へ送る本文。
        """

        program = reservation.program
        duration_seconds = (program.end_time - program.start_time).total_seconds()
        duration_str = self._format_duration_seconds(duration_seconds)

        # 番組概要を 200 文字に制限する
        description = program.description
        if len(description) > 200:
            description = description[:200] + '...'

        return f"""{heading}

📹 **番組情報**
タイトル：{program.title}
チャンネル：{reservation.channel.name}
放送時間：{program.start_time.strftime('%Y/%m/%d %H:%M')} - {program.end_time.strftime('%H:%M')}
長さ：{duration_str}

📝 **番組概要**
{description}"""


    @staticmethod
    def _format_duration_seconds(duration_seconds: float) -> str:
        """
        秒数を「○時間○分」形式の文字列にする

        Args:
            duration_seconds (float): 秒数。

        Returns:
            str: 整形された時間。
        """

        duration_hours = int(duration_seconds // 3600)
        duration_minutes = int((duration_seconds % 3600) // 60)
        if duration_hours > 0:
            return f'{duration_hours}時間{duration_minutes}分'
        return f'{duration_minutes}分'

    async def send_test(self, recorded_program: schemas.RecordedProgram) -> None:
        """テスト通知を送信"""

        message = "🔔 **通知設定テスト**\n\n" + self._build_recording_message(
            recorded_program,
            heading = '✅ **録画が完了しました**',
        )

        try:
            await self._send_text_message(message, recorded_program)
        except Exception as ex:
            logging.warning(f'Telegram テスト通知の送信に失敗しました: {ex}')
            raise

    def _build_recording_message(
        self,
        recorded_program: schemas.RecordedProgram,
        heading: str,
        quality_summary: str | None = None,
    ) -> str:
        """
        録画番組情報からメッセージテキストを構築する

        Args:
            recorded_program (schemas.RecordedProgram): 録画番組情報。
            heading (str): 先頭に付ける見出し。
            quality_summary (str | None): 録画品質の要約。品質情報が無い場合は None。

        Returns:
            str: Telegram へ送る本文。
        """

        # 録画時間を計算
        duration_seconds = (recorded_program.end_time - recorded_program.start_time).total_seconds()
        duration_str = self._format_duration_seconds(duration_seconds)

        # チャンネル名を取得（存在する場合）
        channel_name = recorded_program.channel.name if recorded_program.channel else '不明なチャンネル'

        # 番組概要を200文字に制限
        description = recorded_program.description
        if len(description) > 200:
            description = description[:200] + '...'

        # 録画品質は取得できた場合のみ、番組情報の直後に 1 行で添える
        ## 要約自体が「📊録画品質 D / E / S」の形なので、ここで見出しを重ねない
        quality_line = f'\n{quality_summary}\n' if quality_summary is not None else ''

        # メッセージを構築
        message = f"""{heading}

📹 **番組情報**
タイトル：{recorded_program.title}
チャンネル：{channel_name}
放送時間：{recorded_program.start_time.strftime('%Y/%m/%d %H:%M')} - {recorded_program.end_time.strftime('%H:%M')}
長さ：{duration_str}
{quality_line}
📝 **番組概要**
{description}"""

        return message

    async def _send_text_message(self, text: str, recorded_program: schemas.RecordedProgram | None = None) -> None:
        """テキストメッセージを送信"""

        url = f'{self.base_url}/sendMessage'
        data = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }

        # 録画番組情報がある場合、内联键盘を追加
        if recorded_program and self.config.watch_urls:
            program_id = recorded_program.id
            inline_keyboard_buttons = []
            for watch_url_config in self.config.watch_urls:
                button = {
                    'text': watch_url_config.text,
                    'url': f'{watch_url_config.base_url}/videos/watch/{program_id}'
                }
                inline_keyboard_buttons.append(button)

            inline_keyboard = {
                'inline_keyboard': [inline_keyboard_buttons]
            }
            data['reply_markup'] = json.dumps(inline_keyboard)

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=30)
            response.raise_for_status()

    async def _send_photo_with_caption(
        self,
        caption: str,
        photo_path: anyio.Path,
        recorded_program: schemas.RecordedProgram | None = None,
    ) -> None:
        """サムネイル画像付きでメッセージを送信"""

        url = f'{self.base_url}/sendPhoto'

        # ファイルサイズをチェック（Telegram の制限: 10MB）
        file_size = await photo_path.stat()
        if file_size.st_size > 10 * 1024 * 1024:  # 10MB
            logging.warning(f'サムネイルファイルが大きすぎます ({file_size.st_size} bytes): {photo_path}')
            # サイズが大きい場合はテキストのみ送信
            await self._send_text_message(caption, recorded_program)
            return

        # マルチパートフォームデータを構築
        files = {
            'photo': (photo_path.name, await photo_path.read_bytes(), 'image/webp')
        }
        data = {
            'chat_id': self.chat_id,
            'caption': caption,
            'parse_mode': 'Markdown'
        }

        # 録画番組情報がある場合、内联键盘を追加
        if recorded_program and self.config.watch_urls:
            program_id = recorded_program.id
            inline_keyboard_buttons = []
            for watch_url_config in self.config.watch_urls:
                button = {
                    'text': watch_url_config.text,
                    'url': f'{watch_url_config.base_url}/videos/watch/{program_id}'
                }
                inline_keyboard_buttons.append(button)

            inline_keyboard = {
                'inline_keyboard': [inline_keyboard_buttons]
            }
            data['reply_markup'] = json.dumps(inline_keyboard)

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, files=files, timeout=30)
            response.raise_for_status()


class WebhookNotificationService(NotificationService):
    """
    Webhook を使用した通知サービス
    汎用の JSON を POST するだけなので、Discord / Slack / 自前の受け口などで利用できる
    """

    # Discord の Embed の上限 (これを超えると 400 で拒否される)
    ## ref: https://discord.com/developers/docs/resources/message#embed-object-embed-limits
    ## 番組概要やタイトルは放送内容次第でいくらでも長くなるため、送信前に必ず切り詰める
    EMBED_DESCRIPTION_MAX_LENGTH = 4096
    EMBED_FIELD_VALUE_MAX_LENGTH = 1024
    EMBED_TITLE_MAX_LENGTH = 256
    EMBED_FOOTER_TEXT_MAX_LENGTH = 2048
    EMBED_FIELD_MAX_COUNT = 25
    # Embed 全体で許容される文字数
    ## 個々のフィールドが上限内でも、合計がこれを超えると拒否される
    EMBED_TOTAL_MAX_LENGTH = 6000
    # Webhook の色 (Embed の左側のバー) に使う色
    ## KonomiTV のテーマカラー (primary: #E64F97) を 10 進数に変換した値
    EMBED_COLOR = 0xE64F97

    def __init__(self, config: ServerSettingsNotificationService):
        super().__init__(config)
        # 前後の空白を除去する (コピー & ペースト時の改行・空白で URL が壊れるのを防ぐ)
        self.webhook_url = (config.webhook_url or '').strip()

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """
        文字列を指定された長さに切り詰める

        Discord の上限は「文字数」で判定されるため、Python の文字列長でそのまま数えて良い。

        Args:
            text (str): 対象の文字列。
            max_length (int): 許容される最大文字数。

        Returns:
            str: 切り詰めた文字列 (収まっていればそのまま)。
        """

        # 切り詰めたことを示す "..." の分も含めて上限内に収める
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + '...'

    async def send_event(
        self,
        event: NotificationEvent,
        thumbnail_path: anyio.Path | None = None,
    ) -> None:
        """イベント通知を送信"""

        # この通知先が受け取らないイベントは何もしない
        if self.isEventEnabled(event.type) is False:
            return

        try:
            await self._send_embed(
                payload = self._build_event_payload(event),
                # サムネイルを添付できるのは録画イベントだけ
                thumbnail_path = thumbnail_path if event.recorded_program is not None else None,
            )
        except Exception as ex:
            logging.warning(f'Webhook 通知の送信に失敗しました: {ex}')
            raise

    async def send_test(self, recorded_program: schemas.RecordedProgram) -> None:
        """テスト通知を送信"""

        try:
            await self._send_embed(
                payload = self._build_event_payload(
                    NotificationEvent('RecordingCompleted', recorded_program=recorded_program),
                    is_test = True,
                ),
                thumbnail_path = None,
            )
        except Exception as ex:
            logging.warning(f'Webhook テスト通知の送信に失敗しました: {ex}')
            raise


    def _build_event_payload(self, event: NotificationEvent, is_test: bool = False) -> dict[str, Any]:
        """
        イベント種別に応じた Webhook ペイロードを構築する

        Args:
            event (NotificationEvent): 送信するイベント。
            is_test (bool): テスト通知かどうか。

        Returns:
            dict[str, Any]: Webhook へ送信する JSON ペイロード。
        """

        # イベント種別ごとの見出し
        event_titles: dict[NotificationEventType, str] = {
            'RecordingStarted': '🔴 録画を開始しました',
            'RecordingCompleted': '✅ 録画が完了しました',
            'FileDetected': '📁 新しいファイルを検出しました',
            'FileDeleted': '🗑 録画ファイルが削除されました',
            'EncodeCompleted': (
                '⚠️ エンコードに失敗しました'
                if event.encode_info is not None and event.encode_info.is_failed is True
                else '🎬 エンコードが完了しました'
            ),
            'ReservationAdded': '🗓 録画予約を追加しました',
            'ReservationDeleted': '🗑 録画予約を削除しました',
        }
        title = '🔔 通知設定テスト' if is_test else event_titles[event.type]

        # 録画イベントは録画番組、予約イベントは予約情報からフィールドを組み立てる
        if event.recorded_program is not None:
            return self._build_recording_payload(
                event.recorded_program,
                title,
                quality_summary = event.GetQualitySummary(),
            )
        assert event.reservation is not None
        return self._build_reservation_payload(event.reservation, title)

    @staticmethod
    def _format_duration_seconds(duration_seconds: float) -> str:
        """
        秒数を「○時間○分」形式の文字列にする

        Args:
            duration_seconds (float): 秒数。

        Returns:
            str: 整形された時間。
        """

        duration_hours = int(duration_seconds // 3600)
        duration_minutes = int((duration_seconds % 3600) // 60)
        if duration_hours > 0:
            return f'{duration_hours}時間{duration_minutes}分'
        return f'{duration_minutes}分'

    def _format_duration(self, recorded_program: schemas.RecordedProgram) -> str:
        """
        録画時間を「○時間○分」形式の文字列にする

        Args:
            recorded_program (schemas.RecordedProgram): 録画番組情報。

        Returns:
            str: 整形された録画時間。
        """

        duration_seconds = (recorded_program.end_time - recorded_program.start_time).total_seconds()
        return self._format_duration_seconds(duration_seconds)

    def _build_watch_links(self, recorded_program: schemas.RecordedProgram) -> list[dict[str, Any]]:
        """
        視聴リンクを Webhook のフィールド用に組み立てる

        Args:
            recorded_program (schemas.RecordedProgram): 録画番組情報。

        Returns:
            list[dict[str, Any]]: 視聴リンクのリスト (未設定の場合は空リスト)。
        """

        # 録画 ID が確定していない場合は視聴ページを開けないため、リンク自体を生成しない
        if recorded_program.id < 0:
            return []
        return [
            {
                # フィールド名も上限があるため、長いボタンテキストでリクエスト全体が弾かれないよう切り詰める
                'name': self._truncate(watch_url_config.text, self.EMBED_TITLE_MAX_LENGTH),
                'value': self._truncate(
                    f'[視聴する]({watch_url_config.base_url}/videos/watch/{recorded_program.id})',
                    self.EMBED_FIELD_VALUE_MAX_LENGTH,
                ),
                'inline': True,
            }
            for watch_url_config in self.config.watch_urls
        ]

    def _build_recording_payload(
        self,
        recorded_program: schemas.RecordedProgram,
        title: str,
        quality_summary: str | None = None,
    ) -> dict[str, Any]:
        """
        録画番組情報から Webhook へ POST する JSON を構築する

        Discord の Webhook が受け付ける `content` / `embeds` 形式で組み立てる。
        Discord はこの形式以外の未知のキーを無視するため、Slack など他のサービスでも
        受け取った側で読み替えられる。

        Args:
            recorded_program (schemas.RecordedProgram): 録画番組情報。
            title (str): Embed の見出し。
            quality_summary (str | None): 録画品質の要約。品質情報が無い場合は None。

        Returns:
            dict[str, Any]: Webhook へ送信する JSON ペイロード。
        """

        channel_name = recorded_program.channel.name if recorded_program.channel else '不明なチャンネル'

        # 番組名と番組概要を結合した本文を作る
        ## Discord の Embed の上限は「description 全体」に対して掛かるため、結合後にまとめて切り詰める
        description = self._truncate(
            f'**{recorded_program.title}**\n\n{recorded_program.description}',
            self.EMBED_DESCRIPTION_MAX_LENGTH,
        )

        fields: list[dict[str, Any]] = [
            {
                'name': 'チャンネル',
                'value': self._truncate(channel_name, self.EMBED_FIELD_VALUE_MAX_LENGTH),
                'inline': True,
            },
            {'name': '放送時間', 'value': (
                f'{recorded_program.start_time.strftime("%Y/%m/%d %H:%M")} - '
                f'{recorded_program.end_time.strftime("%H:%M")}'
            ), 'inline': True},
            {'name': '長さ', 'value': self._format_duration(recorded_program), 'inline': True},
        ]
        # 録画品質は取得できた場合のみフィールドとして添える
        ## 品質は番組情報より補足的なので、チャンネル・放送時間・長さの後ろに置く
        ## 要約には「📊録画品質」が含まれるため、フィールド名は D/E/S の内訳だけにする
        if quality_summary is not None:
            fields.append({
                'name': 'D / E / S',
                'value': self._truncate(
                    quality_summary.removeprefix('📊録画品質 '),
                    self.EMBED_FIELD_VALUE_MAX_LENGTH,
                ),
                'inline': False,
            })
        # 視聴リンクは設定されている場合のみフィールドとして並べる
        ## フィールド数の上限を超えると Embed 全体が拒否されるため、残り枠だけに収める
        fields.extend(self._build_watch_links(recorded_program)[:self.EMBED_FIELD_MAX_COUNT - len(fields)])

        # フィールドの合計文字数にも上限があるため、はみ出す場合は先頭から順に残して後ろを落とす
        fields = self._fit_fields_within_total_limit(fields, len(description) + len(title))

        return {
            # メンションを有効にすると通知がうるさいため、Embed だけを送る
            'embeds': [{
                'title': title,
                'description': description,
                'color': self.EMBED_COLOR,
                'fields': fields,
                'footer': {'text': 'KonomiTV'},
            }],
            # Discord では Embed 内のリンクをそのまま開けるため、メンション制御だけ明示する
            'allowed_mentions': {'parse': []},
        }

    def _build_reservation_payload(self, reservation: schemas.Reservation, title: str) -> dict[str, Any]:
        """
        予約情報から Webhook へ POST する JSON を構築する

        Args:
            reservation (schemas.Reservation): 予約情報。
            title (str): Embed の見出し。

        Returns:
            dict[str, Any]: Webhook へ送信する JSON ペイロード。
        """

        program = reservation.program
        description = self._truncate(
            f'**{program.title}**\n\n{program.description}',
            self.EMBED_DESCRIPTION_MAX_LENGTH,
        )

        fields: list[dict[str, Any]] = [
            {
                'name': 'チャンネル',
                'value': self._truncate(reservation.channel.name, self.EMBED_FIELD_VALUE_MAX_LENGTH),
                'inline': True,
            },
            {'name': '放送時間', 'value': (
                f'{program.start_time.strftime("%Y/%m/%d %H:%M")} - '
                f'{program.end_time.strftime("%H:%M")}'
            ), 'inline': True},
            {'name': '長さ', 'value': self._format_duration_seconds(
                (program.end_time - program.start_time).total_seconds(),
            ), 'inline': True},
        ]
        # 予約 ID は視聴ページを持たないため、リンクではなく素の値をフィールドとして添える
        fields.append({'name': '予約 ID', 'value': str(reservation.id), 'inline': True})
        fields = self._fit_fields_within_total_limit(fields, len(description) + len(title))

        return {
            'embeds': [{
                'title': title,
                'description': description,
                'color': self.EMBED_COLOR,
                'fields': fields,
                'footer': {'text': 'KonomiTV'},
            }],
            'allowed_mentions': {'parse': []},
        }

    def _fit_fields_within_total_limit(
        self,
        fields: list[dict[str, Any]],
        base_length: int,
    ) -> list[dict[str, Any]]:
        """
        フィールドの合計文字数が Embed 全体の上限に収まるよう、後ろのフィールドから間引く

        チャンネル・放送時間・長さは通知の要なので、後ろに追加される視聴リンクから削る。

        Args:
            fields (list[dict[str, Any]]): 組み立て済みのフィールド。
            base_length (int): title と description が占める文字数。

        Returns:
            list[dict[str, Any]]: 上限に収まるフィールドのリスト。
        """

        # フィールドが無い場合でも、合計上限を超えていれば後続の処理に任せる (タイトル・本文は別途切り詰め済み)
        total_length = base_length + sum(
            len(str(field['name'])) + len(str(field['value'])) for field in fields
        )
        while fields and total_length > self.EMBED_TOTAL_MAX_LENGTH:
            # 末尾 (視聴リンク) から落とし、その分を合計文字数から差し引く
            removed = fields.pop()
            total_length -= len(str(removed['name'])) + len(str(removed['value']))
        return fields

    async def _send_embed(
        self,
        payload: dict[str, Any],
        thumbnail_path: anyio.Path | None = None,
    ) -> None:
        """
        Webhook へペイロードを POST する

        Args:
            payload (dict[str, Any]): 送信する JSON ペイロード。
            thumbnail_path (anyio.Path | None): サムネイル画像のパス (存在する場合のみ添付する)。

        Returns:
            None

        Raises:
            ValueError: Webhook URL が設定されていない場合。
            httpx.HTTPStatusError: Webhook がエラーを返した場合。
        """

        # Webhook URL が未設定の場合は送信しようがないため、明示的に失敗させる
        if self.webhook_url == '':
            raise ValueError('Webhook URL が設定されていません')

        # サムネイルが存在する場合は Embed の画像として添付する
        ## 添付ファイルを送る場合は multipart/form-data にし、JSON は payload_json へ入れる必要がある
        if thumbnail_path is not None and await thumbnail_path.exists():
            embed = payload['embeds']
            if isinstance(embed, list) and len(embed) > 0 and isinstance(embed[0], dict):
                embed[0]['image'] = {'url': 'attachment://thumbnail.webp'}
            payload = {**payload, 'attachments': [{'id': 0, 'filename': 'thumbnail.webp'}]}
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    data = {'payload_json': json.dumps(payload, ensure_ascii=False)},
                    files = {'files[0]': ('thumbnail.webp', await thumbnail_path.read_bytes(), 'image/webp')},
                    timeout = 30,
                )
                response.raise_for_status()
            return

        # サムネイルが無い場合は JSON をそのまま送る
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=payload, timeout=30)
            response.raise_for_status()


class NotificationManager:
    """
    複数の通知サービスを管理するクラス
    """

    def __init__(self, service_configs: list[ServerSettingsNotificationService]):
        self.services: list[NotificationService] = []

        for config in service_configs:
            if not config.enabled:
                continue

            if config.type == 'Telegram':
                if config.bot_token and config.chat_id:
                    self.services.append(TelegramNotificationService(config))
                else:
                    logging.warning('Telegram通知が有効ですが、bot_tokenまたはchat_idが設定されていません')
            elif config.type == 'Webhook':
                if config.webhook_url and config.webhook_url.strip():
                    self.services.append(WebhookNotificationService(config))
                else:
                    logging.warning('Webhook通知が有効ですが、webhook_urlが設定されていません')
            elif config.type == 'Slack':
                # 将来的にSlackサポートを追加
                logging.warning('Slack通知は現在サポートされていません')

    async def send_event(
        self,
        event: NotificationEvent,
        thumbnail_path: anyio.Path | None = None
    ) -> None:
        """
        全ての有効な通知サービスにイベント通知を送信する

        Args:
            event (NotificationEvent): 送信するイベント。
            thumbnail_path (anyio.Path | None): サムネイル画像のパス（存在する場合）。

        Returns:
            None
        """

        # どの通知先もこのイベントを受け取らない場合は、送信処理そのものを開始しない
        if not self.services or not any(service.isEventEnabled(event.type) for service in self.services):
            return

        # 全サービスに並列で送信
        ## イベントごとの有効・無効は各サービス側で判定する
        tasks = [
            service.send_event(event, thumbnail_path)
            for service in self.services
        ]

        # エラーが発生してもすべてのサービスに送信を試行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # エラーをログに記録
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                service_type = self.services[i].config.type
                logging.error(f'{service_type}通知の送信に失敗しました: {result}')

    async def send_test(self, recorded_program: schemas.RecordedProgram) -> None:
        """全ての有効な通知サービスにテスト通知を送信"""

        if not self.services:
            raise Exception('有効な通知サービスが設定されていません')

        # 全サービスに並列で送信
        tasks = [
            service.send_test(recorded_program)
            for service in self.services
        ]

        # テスト時はエラーを再発生させる
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # エラーがあれば最初のエラーを再発生
        for result in results:
            if isinstance(result, Exception):
                raise result
