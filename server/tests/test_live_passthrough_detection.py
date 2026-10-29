import unittest
from typing import Any, cast
from unittest.mock import MagicMock

from app.streams.LiveEncodingTask import LiveEncodingTask
from app.streams.StreamEncodingOptions import StreamEncodingOptions


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

    def _should_use(
        self,
        quality: str,
        channel_type: str = 'BS4K',
        backend: str = 'Mirakurun',
        stream_format: str = 'TLV',
    ) -> bool:
        """判定結果を返す。"""

        return LiveEncodingTask.ShouldUseMMTLiveTranscode(
            backend_type = backend,
            channel = self._channel(channel_type),
            quality = quality,
            bs4k_stream_format = cast(Any, stream_format),
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

    def test_mpegts_format_disables_mmt_input(self) -> None:
        """MPEG-TS が届く構成では、通常画質でも MMT/TLV 入力にしない。

        dantto4k などで MPEG-TS へ変換している構成では、デフォルト画質 (1080p など) も
        MPEG-TS で届く。MMT/TLV として入力すると失敗するため、設定に従って切り替える。
        """

        for quality in ('1080p', '720p', '480p', '1080p-60fps'):
            with self.subTest(quality=quality):
                self.assertFalse(self._should_use(quality, stream_format='MPEG-TS'))

    def test_mpegts_format_keeps_non_bs4k_unaffected(self) -> None:
        """BS4K 以外は形式の指定に関係なく MMT/TLV 入力にしない。"""

        self.assertFalse(self._should_use('1080p', channel_type='GR', stream_format='MPEG-TS'))

    def test_tlv_format_enables_mmt_for_all_qualities(self) -> None:
        """TLV の構成では、copy 以外の全画質で MMT/TLV を直接入力する。"""

        for quality in ('1080p', '720p', '480p', '1080p-60fps'):
            with self.subTest(quality=quality):
                self.assertTrue(self._should_use(quality, stream_format='TLV'))


class BS4KStreamFormatSuffixTest(unittest.TestCase):
    """BS4K の入力ストリーム形式がライブストリーム ID に反映されることを検証する。"""

    def test_mpegts_format_adds_suffix(self) -> None:
        """MPEG-TS は TLV と別のライブストリームとして扱う。

        同じ画質名でも入力形式が違うとエンコーダーの起動条件が変わるため、
        ライブストリーム ID を分けて互いのセッションを壊さないようにする。
        """

        options = StreamEncodingOptions(bs4k_stream_format='MPEG-TS')
        self.assertEqual(options.buildSuffix(), '-mpegts')

    def test_tlv_format_adds_no_suffix(self) -> None:
        """TLV は従来と同じライブストリーム ID になる。"""

        options = StreamEncodingOptions(bs4k_stream_format='TLV')
        self.assertEqual(options.buildSuffix(), '')

    def test_mpegts_format_combines_with_other_suffixes(self) -> None:
        """10bit / 24fps と併用しても順序が保たれる。"""

        options = StreamEncodingOptions(
            is_hevc_10bit_enabled = True,
            is_24fps_mode_enabled = True,
            bs4k_stream_format = 'MPEG-TS',
        )
        self.assertEqual(options.buildSuffix(), '-10bit-24fps-mpegts')
