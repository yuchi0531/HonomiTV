import re
import unittest
from pathlib import Path


class LiveAspectRatioTest(unittest.TestCase):
    """ライブのエンコードで、出力のアスペクト比が常に 16:9 になることを検証する。

    1080p 系の 1440×1080 だけが 4:3 の画素で、SAR 4:3 を付けて 16:9 として表示する解像度。
    810p / 720p / 540p / 480p はもともと 16:9 の画素なので SAR 1:1 でよい。
    """

    def _source(self) -> str:
        """LiveEncodingTask のソースを返す。

        Returns:
            str: ソースコード。
        """

        path = Path(__file__).resolve().parent.parent / 'app/streams/LiveEncodingTask.py'
        return path.read_text()

    def _sar_for(self, width: int, height: int) -> str:
        """実装と同じ条件で SAR を求める。

        Args:
            width (int): 出力の幅。
            height (int): 出力の高さ。

        Returns:
            str: SAR の文字列。
        """

        return '4/3' if width * 3 == height * 4 else '1/1'

    def test_only_4_3_resolutions_get_4_3_pixel_ratio(self) -> None:
        """4:3 の画素の解像度だけ SAR 4:3 を使う。

        1440×1080 (1080p / 1080p-60fps) だけが該当する。
        810p 以下はもともと 16:9 の画素なので SAR 1:1 が正しい。
        """

        # (幅, 高さ, 期待する SAR)
        expectations = [
            (1920, 1080, '1/1'),  # フル HD 放送
            (1440, 1080, '4/3'),  # 1080p / 1080p-60fps (4:3 の画素)
            (1440, 810, '1/1'),   # 810p
            (1280, 720, '1/1'),   # 720p
            (960, 540, '1/1'),    # 540p
            (854, 480, '1/1'),    # 480p
        ]
        for width, height, expected in expectations:
            with self.subTest(resolution=f'{width}x{height}'):
                self.assertEqual(self._sar_for(width, height), expected)

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
        """解像度から SAR を決めている。"""

        source = self._source()
        self.assertIn("video_sar = '4/3' if video_width * 3 == video_height * 4 else '1/1'", source)
