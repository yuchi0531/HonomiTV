import re
import unittest
from pathlib import Path


class LiveAspectRatioTest(unittest.TestCase):
    """ライブのエンコードで、出力のアスペクト比が 16:9 になることを検証する。

    1440×1080 は 4:3 の画素に SAR 4:3 を付けて 16:9 として表示する解像度。
    SAR を明示しないと正方形画素として扱われ、16:9 の画面で横に黒帯が出る。
    """

    def _source(self) -> str:
        """LiveEncodingTask のソースを返す。

        Returns:
            str: ソースコード。
        """

        path = Path(__file__).resolve().parent.parent / 'app/streams/LiveEncodingTask.py'
        return path.read_text()

    def test_scaled_output_sets_pixel_aspect_ratio(self) -> None:
        """scale を伴う全ての映像フィルタで SAR を明示する。"""

        source = self._source()
        # scale=... を含む -vf は必ず setsar を伴う
        for match in re.finditer(r"'-vf ([^']+)'", source):
            filter_chain = match.group(1)
            if 'scale={video_width}' in filter_chain:
                self.assertIn(
                    'setsar={video_sar}',
                    filter_chain,
                    f'SAR が未指定のフィルタがあります: {filter_chain}',
                )

    def test_pixel_aspect_ratio_depends_on_resolution(self) -> None:
        """1440×1080 では SAR 4:3、正方形画素の解像度では SAR 1:1 を使う。"""

        source = self._source()
        self.assertIn("video_sar = '4/3' if video_width * 3 == video_height * 4 else '1/1'", source)
