from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app import logging
from app.config import Config
from app.constants import HTTPX_CLIENT, JST


# Amatsukaze のキュー API のパス
## Web UI のポート (既定 32769) で JSON を返す
AMATSUKAZE_QUEUE_PATH = '/api/queue'
# API のタイムアウト (秒)
## キューは数百件になることがあり、応答がやや重いため短すぎない値にする
AMATSUKAZE_API_TIMEOUT_SECONDS = 10.0


@dataclass(slots=True, frozen=True)
class AmatsukazeEncodedItem:
    """
    Amatsukaze がエンコードを完了した 1 件分の情報。

    Attributes:
        item_id (int): Amatsukaze のキューアイテム ID。
        source_path (str): エンコード元の録画ファイルパス。
        output_dir (str): 出力先のディレクトリ。
        file_name (str): 出力ファイル名。
        service_name (str): 放送局名。
        finished_at (datetime | None): エンコード完了時刻。
        is_failed (bool): エンコードに失敗したかどうか。
    """

    item_id: int
    source_path: str
    output_dir: str
    file_name: str
    service_name: str
    finished_at: datetime | None
    is_failed: bool


async def FetchAmatsukazeQueue() -> list[dict[str, Any]] | None:
    """
    Amatsukaze のキュー API から現在のアイテム一覧を取得する。

    Returns:
        list[dict[str, Any]] | None: キューアイテムの一覧。無効・失敗時は None。
    """

    config = Config()
    amatsukaze = config.notifications.amatsukaze
    # 無効の場合は API を叩かない
    if amatsukaze.enabled is False:
        return None

    url = f'{str(amatsukaze.url).rstrip("/")}{AMATSUKAZE_QUEUE_PATH}'
    try:
        async with HTTPX_CLIENT() as client:
            response = await client.get(url, timeout=AMATSUKAZE_API_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
    except Exception as ex:
        # Amatsukaze が落ちていても録画や通知の他の機能は動かし続けたいので、例外は握りつぶす
        logging.warning(f'[AmatsukazeClient] Failed to fetch the queue from Amatsukaze. [url: {url}]', exc_info=ex)
        return None

    items = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        logging.warning(f'[AmatsukazeClient] Unexpected queue response. [url: {url}]')
        return None
    return [item for item in items if isinstance(item, dict)]


def ParseAmatsukazeItems(items: list[dict[str, Any]]) -> dict[int, AmatsukazeEncodedItem]:
    """
    Amatsukaze のキューアイテムを、通知に必要な情報へ変換する。

    Args:
        items (list[dict[str, Any]]): キュー API の items。

    Returns:
        dict[int, AmatsukazeEncodedItem]: アイテム ID をキーにした変換結果。
    """

    parsed: dict[int, AmatsukazeEncodedItem] = {}
    for item in items:
        item_id = item.get('id')
        if not isinstance(item_id, int):
            continue
        state = str(item.get('state') or '')
        # 完了と失敗だけを通知対象にする (待機中・実行中は通知しない)
        if state not in ('Complete', 'Failed', 'PreFailed'):
            continue

        finished_at = _ParseAmatsukazeDateTime(item.get('encodeFinish'))
        parsed[item_id] = AmatsukazeEncodedItem(
            item_id = item_id,
            source_path = str(item.get('srcPath') or ''),
            output_dir = str(item.get('outDir') or ''),
            file_name = str(item.get('fileName') or ''),
            service_name = str(item.get('serviceName') or ''),
            finished_at = finished_at,
            is_failed = state != 'Complete',
        )
    return parsed


def _ParseAmatsukazeDateTime(value: Any) -> datetime | None:
    """
    Amatsukaze が返す日時文字列を datetime に変換する。

    Args:
        value (Any): 日時文字列 (例: "2026-08-20T03:47:46.4606755+09:00")。

    Returns:
        datetime | None: 変換結果。解釈できない場合は None。
    """

    if not isinstance(value, str) or value == '':
        return None
    # 小数秒の桁数が .NET 由来で 7 桁になるため、Python が解釈できる 6 桁へ丸める
    normalized = value
    if '.' in normalized:
        head, _, tail = normalized.partition('.')
        # タイムゾーン部分を分離してから小数秒を切り詰める
        tz_index = max(tail.find('+'), tail.find('-'))
        if tz_index >= 0:
            fraction, timezone = tail[:tz_index], tail[tz_index:]
            normalized = f'{head}.{fraction[:6]}{timezone}'
        else:
            normalized = f'{head}.{tail[:6]}'
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    # タイムゾーンが無い場合は JST とみなす
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


class AmatsukazeMonitor:
    """
    Amatsukaze のキューを定期的に確認し、新たにエンコードが完了したアイテムを通知する。

    通知済みのアイテム ID を保持し、同じアイテムを二重に通知しない。
    """

    def __init__(self) -> None:
        """
        Amatsukaze の監視状態を初期化する。
        """

        # 通知済みの Amatsukaze アイテム ID
        ## 起動直後に既存の完了済みアイテムをまとめて通知しないため、初回取得分は記録だけして通知しない
        self._notified_item_ids: set[int] = set()
        # 初回のキュー取得が完了したかどうか
        self._is_initialized = False
        # 実行中の監視タスク
        self._is_running = False

    def _SelectNewItems(self, items: dict[int, AmatsukazeEncodedItem]) -> list[AmatsukazeEncodedItem]:
        """
        今回新たに完了したアイテムを選ぶ。

        Args:
            items (dict[int, AmatsukazeEncodedItem]): 今回取得したアイテム。

        Returns:
            list[AmatsukazeEncodedItem]: 新たに完了したアイテム。
        """

        new_items = [
            item for item_id, item in items.items()
            if item_id not in self._notified_item_ids
        ]
        # 初回は既存の完了済みを通知せず、記録だけ行う
        if self._is_initialized is False:
            self._notified_item_ids.update(items.keys())
            self._is_initialized = True
            if len(new_items) > 0:
                logging.info(
                    f'[AmatsukazeMonitor] Skipped notifying existing items on startup. '
                    f'[count: {len(new_items)}]',
                )
            return []

        self._notified_item_ids.update(items.keys())
        return new_items

    async def PollOnce(self) -> list[AmatsukazeEncodedItem]:
        """
        1 回だけキューを確認し、新たに完了したアイテムを返す。

        Returns:
            list[AmatsukazeEncodedItem]: 新たに完了したアイテム。
        """

        raw_items = await FetchAmatsukazeQueue()
        if raw_items is None:
            return []
        return self._SelectNewItems(ParseAmatsukazeItems(raw_items))

    async def run(self) -> None:
        """
        設定された間隔でキューを確認し続ける。

        Returns:
            None
        """

        if self._is_running is True:
            return
        self._is_running = True
        try:
            while self._is_running is True:
                try:
                    new_items = await self.PollOnce()
                    if len(new_items) > 0:
                        await self._NotifyEncodedItems(new_items)
                except asyncio.CancelledError:
                    raise
                except Exception as ex:
                    # 監視を止めずに次の周期で再試行する
                    logging.error('[AmatsukazeMonitor] Error while polling Amatsukaze.', exc_info=ex)

                config = Config()
                await asyncio.sleep(config.notifications.amatsukaze.poll_interval_seconds)
        finally:
            self._is_running = False

    def stop(self) -> None:
        """
        監視を停止する。

        Returns:
            None
        """

        self._is_running = False

    async def _NotifyEncodedItems(self, items: list[AmatsukazeEncodedItem]) -> None:
        """
        エンコード完了・失敗を通知する。

        Args:
            items (list[AmatsukazeEncodedItem]): 新たに完了したアイテム。

        Returns:
            None
        """

        from app.utils.NotificationService import NotificationEvent, NotificationManager

        config = Config()
        manager = NotificationManager(config.notifications.services)
        for item in items:
            # 失敗も通知する。失敗に気付かないと録画が残ったままになるため
            event_type = 'EncodeCompleted'
            logging.info(
                f'[AmatsukazeMonitor] Amatsukaze item finished. '
                f'[item_id: {item.item_id}, failed: {item.is_failed}, file: {item.file_name}]',
            )
            await manager.send_event(
                NotificationEvent(
                    event_type,
                    encode_info = item,
                ),
            )
