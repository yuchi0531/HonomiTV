import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from puremagic import PureError

from app.routers.CapturesRouter import router


def BuildApp() -> FastAPI:
    """
    テスト用のアプリを組み立てる。

    Returns:
        FastAPI: キャプチャルーターを登録したアプリ。
    """

    app = FastAPI()
    app.include_router(router)
    return app


class CaptureUploadValidationTest(unittest.TestCase):
    """キャプチャのアップロードで、不正なデータを 422 として扱うことを検証する。"""

    def test_empty_file_returns_422(self) -> None:
        """空のファイルは 500 ではなく 422 を返す。

        puremagic は空のファイルで ValueError を投げる。これを捕捉しないと
        500 + traceback になり、クライアントが detail で分岐できない。
        """

        with TestClient(BuildApp()) as client:
            response = client.post(
                '/api/captures',
                files = {'image': ('empty.jpg', b'', 'image/jpeg')},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_non_image_file_returns_422(self) -> None:
        """画像でないデータは 422 を返す。

        puremagic が PureError を投げるケース。
        """

        with patch(
            'app.routers.CapturesRouter.puremagic.magic_stream',
            side_effect = PureError('cannot detect'),
        ):
            with TestClient(BuildApp()) as client:
                response = client.post(
                    '/api/captures',
                    files = {'image': ('note.txt', b'hello world', 'text/plain')},
                )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_index_error_returns_422(self) -> None:
        """puremagic が空のリストを返した場合も 422 を返す。"""

        with patch(
            'app.routers.CapturesRouter.puremagic.magic_stream',
            return_value = [],
        ):
            with TestClient(BuildApp()) as client:
                response = client.post(
                    '/api/captures',
                    files = {'image': ('unknown.bin', b'\x00\x01', 'application/octet-stream')},
                )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_unsupported_image_type_returns_422(self) -> None:
        """JPEG / PNG 以外の画像は 422 を返す。"""

        with TestClient(BuildApp()) as client:
            response = client.post(
                '/api/captures',
                files = {'image': ('image.gif', b'GIF89a' + b'\x00' * 32, 'image/gif')},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_valid_png_is_saved(self) -> None:
        """正当な PNG は保存処理まで進む。

        保存先が無い環境では 422 (保存失敗) になるが、検証で弾かれていないことを確認する。
        """

        # 1x1 の最小 PNG
        png_bytes = bytes.fromhex(
            '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
            '890000000a49444154789c6300010000050001'
            '0d0a2db40000000049454e44ae426082',
        )
        # 保存先の設定は Config() から読むため、テストでは空のフォルダ一覧を返す
        fake_config = type('Config', (), {
            'capture': type('Capture', (), {'upload_folders': []})(),
        })()
        with (
            patch('app.routers.CapturesRouter.Config', return_value = fake_config),
            TestClient(BuildApp()) as client,
        ):
            response = client.post(
                '/api/captures',
                files = {'image': ('image.png', png_bytes, 'image/png')},
            )

        # 画像形式の検証は通っているため、エラーになるとしても「不正な画像」ではない
        if response.status_code != 204:
            self.assertNotEqual(response.json()['detail'], 'Please upload JPEG or PNG image')
