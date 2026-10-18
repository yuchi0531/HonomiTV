import unittest
from unittest.mock import AsyncMock

from app import schemas
from app.routers.ReservationsRouter import (
    EncodeEDCBRecSettingData,
    GetEDCBDefaultBatFilePath,
)


def BuildRecordSettings(**overrides: object) -> schemas.RecordSettings:
    """
    検証用の最小限の録画設定を組み立てる。

    Args:
        **overrides (object): 既定値から差し替えるフィールド。

    Returns:
        schemas.RecordSettings: 検証用の録画設定。
    """

    values: dict[str, object] = {
        'is_enabled': True,
        'recording_mode': 'SpecifiedService',
        'recording_start_margin': 5.0,
        'recording_end_margin': 2.0,
        'caption_recording_mode': 'Enable',
        'data_broadcasting_recording_mode': 'Disable',
        'post_recording_mode': 'Nothing',
        'post_recording_bat_file_path': None,
        'is_event_relay_follow_enabled': False,
        'is_exact_recording_enabled': False,
        'is_oneseg_separate_output_enabled': False,
        'is_sequential_recording_in_single_file_enabled': False,
        'forced_tuner_id': None,
        'recording_folders': [],
    }
    values.update(overrides)
    return schemas.RecordSettings.model_validate(values)


def BuildEpgTimerSrvIni(bat_file_path: str | None) -> bytes:
    """
    EDCB が返す EpgTimerSrv.ini を模擬したバイト列を組み立てる。

    Args:
        bat_file_path (str | None): [REC_DEF] に設定する BatFilePath。None なら項目自体を書かない。

    Returns:
        bytes: cp932 でエンコードした ini データ。
    """

    lines = ['[SET]', 'StartMargin=5', '', '[REC_DEF]', 'SetName=デフォルト', 'RecMode=1']
    if bat_file_path is not None:
        lines.append(f'BatFilePath={bat_file_path}')
    return ('\n'.join(lines) + '\n').encode('cp932')


class DefaultBatFilePathTest(unittest.IsolatedAsyncioTestCase):
    """予約作成時に EDCB のデフォルト bat パスを尊重することを検証する。"""

    async def test_returns_default_bat_path_from_edcb(self) -> None:
        """EpgTimerSrv.ini の [REC_DEF] BatFilePath をそのまま返す。"""

        edcb = AsyncMock()
        edcb.sendFileCopy2.return_value = [
            {'name': 'EpgTimerSrv.ini', 'data': BuildEpgTimerSrvIni('/home/diga/amatsukaze/AddTask.sh')},
        ]

        self.assertEqual(await GetEDCBDefaultBatFilePath(edcb), '/home/diga/amatsukaze/AddTask.sh')

    async def test_returns_empty_when_section_or_key_is_missing(self) -> None:
        """設定が無い場合は空文字列を返し、例外にはしない。"""

        edcb = AsyncMock()
        edcb.sendFileCopy2.return_value = [
            {'name': 'EpgTimerSrv.ini', 'data': BuildEpgTimerSrvIni(None)},
        ]

        self.assertEqual(await GetEDCBDefaultBatFilePath(edcb), '')

    async def test_returns_empty_when_ini_cannot_be_fetched(self) -> None:
        """ini の取得に失敗しても予約作成を妨げないよう空文字列を返す。"""

        edcb = AsyncMock()
        edcb.sendFileCopy2.return_value = None

        self.assertEqual(await GetEDCBDefaultBatFilePath(edcb), '')

    async def test_uses_edcb_default_when_no_explicit_bat_path(self) -> None:
        """bat パスの明示指定が無い場合は EDCB のデフォルトを送る。

        空文字を送ると EDCB の設定が上書きされ、録画後の自動処理が動かなくなる。
        """

        edcb = AsyncMock()
        edcb.sendFileCopy2.return_value = [
            {'name': 'EpgTimerSrv.ini', 'data': BuildEpgTimerSrvIni('/home/diga/amatsukaze/AddTask.sh')},
        ]

        encoded = await EncodeEDCBRecSettingData(BuildRecordSettings(), edcb)

        self.assertEqual(encoded['bat_file_path'], '/home/diga/amatsukaze/AddTask.sh')

    async def test_keeps_explicit_bat_path(self) -> None:
        """明示的に指定された bat パスはデフォルトで上書きしない。"""

        edcb = AsyncMock()
        edcb.sendFileCopy2.return_value = [
            {'name': 'EpgTimerSrv.ini', 'data': BuildEpgTimerSrvIni('/home/diga/amatsukaze/AddTask.sh')},
        ]

        encoded = await EncodeEDCBRecSettingData(
            BuildRecordSettings(post_recording_bat_file_path='/custom/run.sh'),
            edcb,
        )

        self.assertEqual(encoded['bat_file_path'], '/custom/run.sh')
        # 明示指定がある場合は ini の取得すら行わない
        edcb.sendFileCopy2.assert_not_awaited()
