import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

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

    def test_unsupported_extension_returns_422(self) -> None:
        """JPEG / PNG 以外の拡張子は 422 を返す。

        JPEG は末尾に任意のデータを付けても画像として読めるため、中身の検査だけでは
        実行できるファイルとして保存できてしまう。拡張子で弾く。
        """

        with TestClient(BuildApp()) as client:
            response = client.post(
                '/api/captures',
                files = {'image': ('note.txt', b'hello world', 'text/plain')},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_empty_image_returns_422(self) -> None:
        """中身が空の画像は 422 を返す。"""

        with TestClient(BuildApp()) as client:
            response = client.post(
                '/api/captures',
                files = {'image': ('empty.jpg', b'', 'image/jpeg')},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_broken_image_returns_422(self) -> None:
        """画像として読めないデータは 422 を返す。"""

        with TestClient(BuildApp()) as client:
            response = client.post(
                '/api/captures',
                files = {'image': ('broken.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 32, 'image/png')},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Please upload JPEG or PNG image')

    def test_too_large_image_returns_413(self) -> None:
        """上限を超える大きさの画像は 413 を返す。"""

        with patch('app.routers.CapturesRouter.CAPTURE_UPLOAD_MAX_SIZE', 8):
            with TestClient(BuildApp()) as client:
                response = client.post(
                    '/api/captures',
                    files = {'image': ('large.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 64, 'image/jpeg')},
                )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['detail'], 'Image file is too large')
