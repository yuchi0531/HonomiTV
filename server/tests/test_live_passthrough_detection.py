import unittest


class LiveCopyQualityTest(unittest.TestCase):
    """dantto4k などで HEVC へ変換済みの MPEG-TS を、ライブでも再エンコードせず扱えることを検証する。"""

    def test_copy_quality_is_accepted_for_live(self) -> None:
        """ライブ API が copy 品質を受け付ける。

        BS4K の生ストリームが MPEG-TS (HEVC) で届く構成で、TLV パススルーの代わりに使う。
        """

        from app.streams.StreamEncodingOptions import SplitLiveQualityAndEncodingOptions

        stream_quality = SplitLiveQualityAndEncodingOptions('copy')
        self.assertIsNotNone(stream_quality)
        assert stream_quality is not None
        self.assertEqual(stream_quality.quality, 'copy')

    def test_regular_live_quality_still_works(self) -> None:
        """通常の画質指定はこれまでどおり分解できる。"""

        from app.streams.StreamEncodingOptions import SplitLiveQualityAndEncodingOptions

        stream_quality = SplitLiveQualityAndEncodingOptions('1080p')
        self.assertIsNotNone(stream_quality)
        assert stream_quality is not None
        self.assertEqual(stream_quality.quality, '1080p')
