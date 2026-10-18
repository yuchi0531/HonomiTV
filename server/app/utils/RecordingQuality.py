from __future__ import annotations

from dataclasses import dataclass

from app import logging
from app.config import ServerSettings
from app.utils.edcb.CtrlCmdUtil import CtrlCmdUtil
from app.utils.RecordingStatusProvider import AreRecordingPathsEquivalent


@dataclass(slots=True, frozen=True)
class RecordingQuality:
    """
    EDCB が記録した録画品質の統計。

    Attributes:
        drops (int): ドロップしたパケット数。0 より大きい場合は録画が途切れている可能性がある。
        scrambles (int): スクランブル解除に失敗したパケット数。0 より大きい場合は映像が乱れる可能性がある。
        error_info (str): EDCB が記録したエラー情報。空文字列の場合はエラーなし。
    """

    drops: int
    scrambles: int
    error_info: str

    @property
    def error_count(self) -> int:
        """
        エラー情報の件数を返す。

        EDCB の err_info は件数ではなく自由文のため、空でない行の数を件数として扱う。
        1 行のエラー記述なら 1、エラーが無ければ 0 になる。

        Returns:
            int: エラー情報の件数。
        """

        return sum(1 for line in self.error_info.splitlines() if line.strip() != '')

    @property
    def has_problem(self) -> bool:
        """
        録画品質に問題があるかどうかを返す。

        Returns:
            bool: ドロップ・スクランブル・エラー情報のいずれかがある場合は True。
        """

        return self.drops > 0 or self.scrambles > 0 or self.error_count > 0


async def GetEDCBRecordingQuality(file_path: str, config: ServerSettings) -> RecordingQuality | None:
    """
    EDCB の録画済み情報から、指定された録画ファイルの品質統計 (D/E/S) を取得する。

    EDCB の RecFileInfo は録画フォルダのパスを EDCB 側の形式 (Windows のドライブレター付きなど)
    で返すため、KonomiTV 側のパスと比較する際は候補パスへ展開して突き合わせる。

    Args:
        file_path (str): 品質統計を取得したい録画ファイルのパス。
        config (ServerSettings): サーバー設定。

    Returns:
        RecordingQuality | None: 取得できた品質統計。EDCB 以外のバックエンド、
            録画情報が見つからない場合、または取得に失敗した場合は None。
    """

    # D/E/S は EDCB の録画済み情報にしか存在しない
    if config.general.backend != 'EDCB':
        return None

    try:
        edcb = CtrlCmdUtil()
        # 一覧取得は programInfo / errInfo を除く軽量版を使う
        ## drops / scrambles は一覧に含まれるが、err_info は含まれないため該当があれば詳細取得で補う
        rec_file_info_list = await edcb.sendEnumRecInfoBasic()
        if rec_file_info_list is None:
            logging.warning('[RecordingQuality][EDCB] Failed to get recorded file info list.')
            return None

        # KonomiTV 側のパスと一致する録画情報を探す
        ## EDCB はドライブレター付きや別ホスト基準のパスを返すため、候補へ展開して比較する
        matched_info = next(
            (
                rec_file_info for rec_file_info in rec_file_info_list
                if AreRecordingPathsEquivalent(str(rec_file_info.get('rec_file_path', '')), file_path, config)
            ),
            None,
        )
        if matched_info is None:
            return None

        # err_info は一覧取得に含まれないため、詳細取得で補う
        ## 詳細取得に失敗しても、ドロップとスクランブルは一覧の値で通知できるため、
        ## ここだけを個別に保護して品質統計全体を失わないようにする
        error_info = str(matched_info.get('err_info', ''))
        info_id = matched_info.get('id')
        if info_id is not None:
            try:
                detailed_info = await edcb.sendGetRecInfo(int(info_id))
                if detailed_info is not None:
                    error_info = str(detailed_info.get('err_info', ''))
            except Exception as ex:
                logging.warning(f'[RecordingQuality][EDCB] Failed to get recording detail: {ex}')

        return RecordingQuality(
            drops = int(matched_info.get('drops', 0)),
            scrambles = int(matched_info.get('scrambles', 0)),
            error_info = error_info,
        )
    except Exception as ex:
        # 品質統計は通知の補足情報なので、取得できなくても通知自体は送る
        logging.warning(f'[RecordingQuality][EDCB] Failed to get recording quality: {ex}')
        return None
