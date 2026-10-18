# pyright: reportPrivateUsage=false

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.metadata import MetadataAnalyzer as metadata_analyzer_module
from app.metadata.MetadataAnalyzer import MetadataAnalyzer


class DetectScanTypeFromFramesTest(unittest.TestCase):
    """ffprobe の field_order が unknown な録画のスキャン形式判定を検証する。"""

    def _detect(self, ffprobe_result: dict[str, Any] | None) -> str:
        """
        フレーム判定に任意の ffprobe 結果を渡して結果を得る。

        Args:
            ffprobe_result (dict[str, Any] | None): __runFFprobe が返す想定の結果。

        Returns:
            str: 判定されたスキャン形式。
        """

        analyzer = MetadataAnalyzer(Path('/nonexistent/recorded.ts'))
        with (
            patch.object(
                MetadataAnalyzer,
                '_MetadataAnalyzer__runFFprobe',
                return_value = ffprobe_result,
            ),
            # 判定結果はログ出力するため、設定の初期化を要求しないようモックする
            patch.object(metadata_analyzer_module.logging, 'debug'),
        ):
            # 名前マングリングされた内部メソッドを直接検証する
            return analyzer._MetadataAnalyzer__detectScanTypeFromFrames()  # pyright: ignore[reportAttributeAccessIssue]


    def test_all_progressive_frames_are_detected_as_progressive(self) -> None:
        """interlaced_frame が全て 0 ならプログレッシブと判定する。"""

        self.assertEqual(
            self._detect({'frames': [{'interlaced_frame': 0}] * 20}),
            'Progressive',
        )


    def test_all_interlaced_frames_are_detected_as_interlaced(self) -> None:
        """interlaced_frame が全て 1 ならインターレースと判定する。"""

        self.assertEqual(
            self._detect({'frames': [{'interlaced_frame': 1}] * 20}),
            'Interlaced',
        )


    def test_mostly_progressive_frames_are_detected_as_progressive(self) -> None:
        """ごく一部だけ interlaced のフレームが混ざってもプログレッシブと判定する。

        テレシネ混在などで一部だけフラグが立つ映像に yadif を適用すると、
        不要な画質劣化を招くため過半数で判定する。
        """

        frames = [{'interlaced_frame': 0}] * 3593 + [{'interlaced_frame': 1}] * 4
        self.assertEqual(self._detect({'frames': frames}), 'Progressive')


    def test_majority_interlaced_frames_are_detected_as_interlaced(self) -> None:
        """過半数がインターレースならインターレースと判定する。"""

        frames = [{'interlaced_frame': 1}] * 11 + [{'interlaced_frame': 0}] * 9
        self.assertEqual(self._detect({'frames': frames}), 'Interlaced')


    def test_falls_back_to_interlaced_when_frames_are_unavailable(self) -> None:
        """フレーム情報が得られない場合は従来どおりインターレース扱いにする。"""

        self.assertEqual(self._detect(None), 'Interlaced')
        self.assertEqual(self._detect({'frames': []}), 'Interlaced')
        self.assertEqual(self._detect({'frames': [{}, {}]}), 'Interlaced')
