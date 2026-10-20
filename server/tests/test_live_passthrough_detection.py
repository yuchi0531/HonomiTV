import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.LiveStreamsRouter import (
    DetectLiveStreamIsMMTTLV,
    LooksLikeMPEGTSStream,
)


def BuildMPEGTSHead() -> bytes:
    """
    MPEG-TS の先頭バイト列を組み立てる。

    Returns:
        bytes: 188 バイト周期で同期バイト 0x47 が並ぶデータ。
    """

    packet = bytearray(188 * 8)
    for index in range(8):
        packet[index * 188] = 0x47
    return bytes(packet)


def BuildMMTSHead() -> bytes:
    """
    MMT/TLV の先頭バイト列を組み立てる。

    TLV は 0x47 が 188 バイト周期で並ばないため、MPEG-TS と判定されないデータになる。

    Returns:
        bytes: MMT/TLV を模したデータ。
    """

    # 先頭に 0x47 を置きつつ、188 バイト周期では揃わないようにする
    ## 「たまたま先頭が 0x47」なだけで MPEG-TS と誤判定しないことの検証も兼ねる
    data = bytearray(188 * 8)
    data[0] = 0x47
    data[100] = 0x11
    data[377] = 0x47
    return bytes(data)


class LooksLikeMPEGTSStreamTest(unittest.TestCase):
    """ストリームの先頭バイトから MPEG-TS かどうかを判定できることを検証する。"""

    def test_detects_mpegts_by_sync_bytes(self) -> None:
        """188 バイト周期で 0x47 が並べば MPEG-TS と判定する。"""

        self.assertTrue(LooksLikeMPEGTSStream(BuildMPEGTSHead()))

    def test_does_not_mistake_mmts_for_mpegts(self) -> None:
        """先頭が 0x47 でも周期が揃っていなければ MPEG-TS と判定しない。"""

        self.assertFalse(LooksLikeMPEGTSStream(BuildMMTSHead()))

    def test_returns_false_for_short_data(self) -> None:
        """判定に足るデータが無い場合は MPEG-TS と判定しない。"""

        self.assertFalse(LooksLikeMPEGTSStream(b''))
        self.assertFalse(LooksLikeMPEGTSStream(b'\x47' * 10))


class DetectLiveStreamIsMMTTLVTest(unittest.IsolatedAsyncioTestCase):
    """BS4K チャンネルのストリーム形式判定を検証する。"""

    async def asyncSetUp(self) -> None:
        """チャンネル判定のキャッシュを毎回初期化する。"""

        from app.routers import LiveStreamsRouter

        LiveStreamsRouter._detected_mmt_tlv_channels.clear()

    def _channel(self, channel_type: str = 'BS4K') -> Any:
        """判定対象のチャンネルを組み立てる。"""

        return MagicMock(id='NID1-SID2', display_channel_id='bs4k101', type=channel_type,
                         network_id=1, service_id=2)

    async def test_returns_true_when_stream_is_mmt_tlv(self) -> None:
        """実際のストリームが MMT/TLV なら True を返す。"""

        response = MagicMock(status=200)
        response.content.read = AsyncMock(return_value=BuildMMTSHead())
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        session.close = AsyncMock()

        with (
            patch('app.routers.LiveStreamsRouter.GetBackendForReceiving', return_value='Mirakurun'),
            patch('app.routers.LiveStreamsRouter.GetMirakurunAPIEndpointURL', return_value='http://mirakurun'),
            patch('app.routers.LiveStreamsRouter.logging'),
            patch('app.routers.LiveStreamsRouter.aiohttp.ClientSession', return_value=session),
        ):
            self.assertTrue(await DetectLiveStreamIsMMTTLV(self._channel()))

    async def test_returns_false_when_stream_is_mpegts(self) -> None:
        """dantto4k などで変換され MPEG-TS が来る場合は False を返す。

        この場合 TLV パススルーは再生できないため、クライアント側で選択肢から外す。
        """

        response = MagicMock(status=200)
        response.content.read = AsyncMock(return_value=BuildMPEGTSHead())
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        session.close = AsyncMock()

        with (
            patch('app.routers.LiveStreamsRouter.GetBackendForReceiving', return_value='Mirakurun'),
            patch('app.routers.LiveStreamsRouter.GetMirakurunAPIEndpointURL', return_value='http://mirakurun'),
            patch('app.routers.LiveStreamsRouter.logging'),
            patch('app.routers.LiveStreamsRouter.aiohttp.ClientSession', return_value=session),
        ):
            self.assertFalse(await DetectLiveStreamIsMMTTLV(self._channel()))

    async def test_returns_false_for_non_mirakurun_backend(self) -> None:
        """Mirakurun 以外では raw-mmts 自体が使えないため False を返す。"""

        with (
            patch('app.routers.LiveStreamsRouter.GetBackendForReceiving', return_value='EDCB'),
            patch('app.routers.LiveStreamsRouter.logging'),
        ):
            self.assertFalse(await DetectLiveStreamIsMMTTLV(self._channel()))

    async def test_result_is_cached_between_calls(self) -> None:
        """同じチャンネルの判定結果はキャッシュし、毎回ストリームを開き直さない。"""

        response = MagicMock(status=200)
        response.content.read = AsyncMock(return_value=BuildMMTSHead())
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        session.close = AsyncMock()

        with (
            patch('app.routers.LiveStreamsRouter.GetBackendForReceiving', return_value='Mirakurun'),
            patch('app.routers.LiveStreamsRouter.GetMirakurunAPIEndpointURL', return_value='http://mirakurun'),
            patch('app.routers.LiveStreamsRouter.logging'),
            patch('app.routers.LiveStreamsRouter.aiohttp.ClientSession', return_value=session),
        ):
            channel = self._channel()
            self.assertTrue(await DetectLiveStreamIsMMTTLV(channel))
            self.assertTrue(await DetectLiveStreamIsMMTTLV(channel))

        # 2 回目はキャッシュから返るため、ストリームは 1 回しか開かない
        self.assertEqual(session.get.await_count, 1)

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
