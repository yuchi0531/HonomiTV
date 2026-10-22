import unittest
from typing import Any
from unittest.mock import MagicMock

from app.streams.LiveEncodingTask import LiveEncodingTask


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


class MMTLiveTranscodeSelectionTest(unittest.TestCase):
    """BS4K ライブで MMT/TLV を直接入力するかどうかの判定を検証する。"""

    def _channel(self, channel_type: str = 'BS4K', is_radio: bool = False) -> Any:
        """判定対象のチャンネルを組み立てる。"""

        return MagicMock(type=channel_type, is_radiochannel=is_radio)

    def _should_use(self, quality: str, channel_type: str = 'BS4K', backend: str = 'Mirakurun') -> bool:
        """判定結果を返す。"""

        return LiveEncodingTask.ShouldUseMMTLiveTranscode(
            backend_type = backend,
            channel = self._channel(channel_type),
            quality = quality,
            debug_mode_ts_path = None,
        )

    def test_bs4k_uses_mmt_for_regular_quality(self) -> None:
        """通常画質の BS4K は MMT/TLV を直接入力する。"""

        self.assertTrue(self._should_use('1080p'))

    def test_copy_does_not_use_mmt_input(self) -> None:
        """copy は MPEG-TS (HEVC) 前提のため MMT/TLV 入力にしない。

        dantto4k などで変換済みの構成では MPEG-TS が届くため、
        MMT/TLV として入力すると「エンコードタスクを起動しています…」のまま止まる。
        """

        self.assertFalse(self._should_use('copy'))

    def test_non_bs4k_channel_does_not_use_mmt(self) -> None:
        """BS4K 以外は MMT/TLV 入力にしない。"""

        self.assertFalse(self._should_use('1080p', channel_type='GR'))

    def test_non_mirakurun_backend_does_not_use_mmt(self) -> None:
        """Mirakurun 以外は MMT/TLV 入力にしない。"""

        self.assertFalse(self._should_use('1080p', backend='EDCB'))
