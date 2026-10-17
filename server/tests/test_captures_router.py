import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from PIL import Image
from tortoise import Tortoise

from app.constants import DATABASE_CONFIG
from app.models.CaptureBookmark import CaptureBookmark
from app.models.CaptureFolder import CaptureFolder
from app.models.Channel import Channel
from app.models.User import User
from app.routers.CapturesRouter import (
    CAPTURE_EXTENSIONS,
    PAGE_SIZE,
    THUMBNAIL_MAX_SIZE,
    FindCaptureFile,
)
from app.routers.CapturesRouter import router as captures_router
from app.routers.UsersRouter import GetCurrentUser


XP_COMMENT_TAG = 0x9C9C


def BuildCaptureMetadata(**overrides: Any) -> dict[str, Any]:
    """
    キャプチャの EXIF XPComment に書き込むメタデータを生成する。

    Args:
        **overrides (Any): 既定値から差し替えるフィールド。

    Returns:
        dict[str, Any]: クライアント側の ICaptureExifData と同じ構造の辞書。
    """

    metadata: dict[str, Any] = {
        'captured_at': '2026-10-17T12:00:00+09:00',
        'captured_playback_position': 125.5,
        'network_id': 32736,
        'service_id': 1024,
        'event_id': 65535,
        'title': 'テストニュース',
        'description': 'テスト用の番組概要',
        'start_time': '2026-10-17T12:00:00+09:00',
        'end_time': '2026-10-17T12:30:00+09:00',
        'duration': 1800.0,
        'caption_text': 'テスト字幕',
        'is_caption_composited': True,
        'is_comment_composited': False,
    }
    metadata.update(overrides)
    return metadata


def WriteCaptureImage(filepath: Path, metadata: dict[str, Any] | None, size: tuple[int, int] = (640, 360)) -> None:
    """
    EXIF XPComment 付きのキャプチャ画像 (JPEG) を書き出す。

    クライアント側の CaptureCompositor と同じく、メタデータは UTF-16-LE の JSON として格納する。

    Args:
        filepath (Path): 書き出すファイルのパス。
        metadata (dict[str, Any] | None): 格納するメタデータ。None の場合は EXIF を書かない。
        size (tuple[int, int]): 画像の幅と高さ。

    Returns:
        None
    """

    image = Image.new('RGB', size, (32, 64, 96))
    if metadata is None:
        image.save(filepath, format='JPEG', quality=90)
        return

    exif = Image.Exif()
    exif[XP_COMMENT_TAG] = json.dumps(metadata, ensure_ascii=False).encode('utf-16-le') + b'\x00\x00'
    image.save(filepath, format='JPEG', quality=90, exif=exif)


class CapturesRouterTest(unittest.IsolatedAsyncioTestCase):
    """キャプチャギャラリー API を、実 SQLite と実ファイルで検証する。"""

    async def asyncSetUp(self) -> None:
        """
        テスト専用の保存先フォルダとメモリ内 SQLite を用意する。

        Returns:
            None
        """

        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_folder = Path(self.temp_dir.name) / 'captures'
        self.upload_folder.mkdir()

        await Tortoise.init(
            db_url = 'sqlite://:memory:',
            modules = {'models': cast(list[str], DATABASE_CONFIG['apps']['models']['models'])},
        )
        await Tortoise.generate_schemas()

        self.user = await User.create(name='viewer', password='x', is_admin=False)
        self.admin = await User.create(name='admin', password='x', is_admin=True)

        # サーバー設定はファイルから読むため、保存先フォルダだけを差し替えた設定で固定する
        config = SimpleNamespace(capture=SimpleNamespace(upload_folders=[str(self.upload_folder)]))
        self.config_patcher = patch('app.routers.CapturesRouter.Config', return_value=config)
        self.config_patcher.start()

    async def asyncTearDown(self) -> None:
        """
        DB 接続・一時フォルダ・設定の差し替えを破棄する。

        Returns:
            None
        """

        await Tortoise.close_connections()
        self.config_patcher.stop()
        self.temp_dir.cleanup()

    def _buildApplication(self, current_user: User) -> FastAPI:
        """
        任意のユーザーをログイン状態として固定した検証用アプリを組み立てる。

        GetCurrentUser だけを差し替え、GetCurrentAdminUser は実装のまま動かす。
        これにより管理者権限の判定 (403) まで実際のコードを通して検証できる。

        Args:
            current_user (User): GetCurrentUser が返すユーザー。

        Returns:
            FastAPI: 認証依存関係を差し替えたアプリケーション。
        """

        application = FastAPI()
        application.include_router(captures_router)
        application.dependency_overrides[GetCurrentUser] = lambda: current_user
        return application

    def _client(self, current_user: User | None = None) -> httpx.AsyncClient:
        """
        検証用アプリへ接続する HTTP クライアントを生成する。

        Args:
            current_user (User | None): ログイン中ユーザー。省略時は一般ユーザー。

        Returns:
            httpx.AsyncClient: ASGI トランスポート経由のクライアント。
        """

        application = self._buildApplication(current_user or self.user)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url='http://test',
        )

    async def test_list_returns_captures_with_exif_metadata_newest_first(self) -> None:
        """一覧が更新日時順に並び、EXIF の番組情報と画像サイズを返す。"""

        WriteCaptureImage(self.upload_folder / 'newer.jpg', BuildCaptureMetadata(title='新しい番組'))
        WriteCaptureImage(self.upload_folder / 'older.jpg', BuildCaptureMetadata(title='古い番組'), size=(320, 180))

        # 更新日時を明示的に与え、ファイルシステムの時刻精度に依存しないようにする
        now = datetime.now(UTC).timestamp()
        os.utime(self.upload_folder / 'newer.jpg', (now, now))
        os.utime(self.upload_folder / 'older.jpg', (now - 3600, now - 3600))

        async with self._client() as client:
            response = await client.get('/api/captures')
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body['total'], 2)
            self.assertEqual([capture['filename'] for capture in body['captures']], ['newer.jpg', 'older.jpg'])

            newest = body['captures'][0]
            self.assertEqual((newest['image_width'], newest['image_height']), (640, 360))
            self.assertEqual(newest['mime_type'], 'image/jpeg')
            self.assertEqual(newest['capture_metadata']['title'], '新しい番組')
            self.assertTrue(newest['capture_metadata']['is_caption_composited'])

            # asc を指定すると並びが反転する
            ascending = await client.get('/api/captures', params={'order': 'asc'})
            self.assertEqual(
                [capture['filename'] for capture in ascending.json()['captures']],
                ['older.jpg', 'newer.jpg'],
            )

    async def test_list_keeps_files_with_broken_or_missing_exif(self) -> None:
        """EXIF が無い・壊れている画像でも一覧から消えず、メタデータだけが null になる。"""

        WriteCaptureImage(self.upload_folder / 'no-exif.jpg', None)
        (self.upload_folder / 'broken.jpg').write_bytes(b'not an image at all')
        (self.upload_folder / 'ignore.txt').write_text('not a capture')

        async with self._client() as client:
            response = await client.get('/api/captures')
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            # 拡張子ホワイトリストにより .txt は一覧に現れない
            self.assertEqual(body['total'], 2)
            filenames = {capture['filename'] for capture in body['captures']}
            self.assertEqual(filenames, {'no-exif.jpg', 'broken.jpg'})
            for capture in body['captures']:
                self.assertIsNone(capture['capture_metadata'])
            # 画像として開けないファイルはサイズ 0 として返す
            broken = next(c for c in body['captures'] if c['filename'] == 'broken.jpg')
            self.assertEqual((broken['image_width'], broken['image_height']), (0, 0))

    async def test_list_paginates_with_fixed_page_size(self) -> None:
        """ページサイズを固定しつつ、total はページネーション前の総数を返す。"""

        for index in range(PAGE_SIZE + 2):
            WriteCaptureImage(self.upload_folder / f'capture-{index:03}.jpg', BuildCaptureMetadata())

        async with self._client() as client:
            first_page = await client.get('/api/captures', params={'page': 1})
            self.assertEqual(first_page.status_code, 200, first_page.text)
            self.assertEqual(first_page.json()['total'], PAGE_SIZE + 2)
            self.assertEqual(len(first_page.json()['captures']), PAGE_SIZE)

            second_page = await client.get('/api/captures', params={'page': 2})
            self.assertEqual(len(second_page.json()['captures']), 2)

            # 1 ページ目と 2 ページ目に重複が無い
            first_filenames = {capture['filename'] for capture in first_page.json()['captures']}
            second_filenames = {capture['filename'] for capture in second_page.json()['captures']}
            self.assertEqual(first_filenames & second_filenames, set())

    async def test_search_matches_filename_program_title_and_channel_name(self) -> None:
        """検索がファイル名・番組名・チャンネル名のいずれでも一致する。"""

        WriteCaptureImage(
            self.upload_folder / 'Capture_サッカー.jpg',
            BuildCaptureMetadata(title='スポーツニュース'),
        )
        WriteCaptureImage(
            self.upload_folder / 'Capture_other.jpg',
            BuildCaptureMetadata(title='天気予報', network_id=32737, service_id=1024),
        )
        await Channel.create(
            id='NID32736-SID1024', display_channel_id='gr011', network_id=32736, service_id=1024,
            transport_stream_id=32736, remocon_id=1, channel_number='011', type='GR',
            name='テスト放送', jikkyo_force=None, is_subchannel=False, is_radiochannel=False,
            is_watchable=True,
        )

        async with self._client() as client:
            by_filename = await client.get('/api/captures', params={'search': 'サッカー'})
            self.assertEqual([c['filename'] for c in by_filename.json()['captures']], ['Capture_サッカー.jpg'])

            by_title = await client.get('/api/captures', params={'search': '天気'})
            self.assertEqual([c['filename'] for c in by_title.json()['captures']], ['Capture_other.jpg'])

            by_channel = await client.get('/api/captures', params={'search': 'テスト放送'})
            self.assertEqual([c['filename'] for c in by_channel.json()['captures']], ['Capture_サッカー.jpg'])

            no_match = await client.get('/api/captures', params={'search': '存在しない番組'})
            self.assertEqual(no_match.json(), {'total': 0, 'captures': []})

    async def test_image_endpoint_serves_full_image_and_thumbnail_with_etag(self) -> None:
        """画像取得 API が原寸・サムネイルを返し、ETag 一致時は 304 を返す。"""

        WriteCaptureImage(self.upload_folder / 'capture.jpg', BuildCaptureMetadata())

        async with self._client() as client:
            full = await client.get('/api/captures/capture.jpg')
            self.assertEqual(full.status_code, 200, full.text)
            self.assertEqual(full.headers['content-type'], 'image/jpeg')
            self.assertIn('etag', full.headers)

            thumbnail = await client.get('/api/captures/capture.jpg', params={'thumbnail': 'true'})
            self.assertEqual(thumbnail.status_code, 200, thumbnail.text)
            with Image.open(io.BytesIO(thumbnail.content)) as image:
                # 長辺がサムネイル上限に収まっている
                self.assertLessEqual(max(image.size), THUMBNAIL_MAX_SIZE)
                self.assertEqual(image.format, 'JPEG')

            # 同じ ETag を送ると本文なしの 304 になる
            not_modified = await client.get(
                '/api/captures/capture.jpg',
                headers={'If-None-Match': full.headers['etag']},
            )
            self.assertEqual(not_modified.status_code, 304)
            self.assertEqual(not_modified.content, b'')

            # サムネイルと原寸は ETag が異なるため、取り違えて 304 にならない
            thumbnail_with_full_etag = await client.get(
                '/api/captures/capture.jpg',
                params={'thumbnail': 'true'},
                headers={'If-None-Match': full.headers['etag']},
            )
            self.assertEqual(thumbnail_with_full_etag.status_code, 200)

    async def test_image_endpoint_rejects_traversal_and_unknown_files(self) -> None:
        """保存先フォルダ外を指す名前や未存在の名前は 404 になり、実ファイルを漏らさない。"""

        WriteCaptureImage(Path(self.temp_dir.name) / 'secret.jpg', BuildCaptureMetadata())

        async with self._client() as client:
            for filename in ['../secret.jpg', '..%2Fsecret.jpg', 'missing.jpg', 'notes.txt']:
                with self.subTest(filename=filename):
                    response = await client.get(f'/api/captures/{filename}')
                    self.assertEqual(response.status_code, 404, response.text)

        self.assertIsNone(FindCaptureFile('../secret.jpg'))
        self.assertIsNone(FindCaptureFile('notes.txt'))
        self.assertIsNone(FindCaptureFile(''))

    async def test_delete_requires_admin_and_cleans_bookmarks(self) -> None:
        """削除は管理者のみ実行でき、削除したキャプチャのブックマークも掃除される。"""

        WriteCaptureImage(self.upload_folder / 'capture.jpg', BuildCaptureMetadata())
        folder = await CaptureFolder.create(user=self.user, name='お気に入り')
        await CaptureBookmark.create(folder=folder, filename='capture.jpg')

        # 一般ユーザーでは削除できない
        async with self._client(self.user) as client:
            denied = await client.delete('/api/captures/capture.jpg')
            self.assertEqual(denied.status_code, 403)
        self.assertTrue((self.upload_folder / 'capture.jpg').is_file())

        # 管理者は削除でき、実ファイルとブックマークが消える
        async with self._client(self.admin) as client:
            deleted = await client.delete('/api/captures/capture.jpg')
            self.assertEqual(deleted.status_code, 204, deleted.text)
            self.assertFalse((self.upload_folder / 'capture.jpg').is_file())
            self.assertEqual(await CaptureBookmark.filter(filename='capture.jpg').count(), 0)

            # 既に無いファイルの削除は 404
            missing = await client.delete('/api/captures/capture.jpg')
            self.assertEqual(missing.status_code, 404)

    async def test_folder_crud_counts_captures_and_enforces_ownership(self) -> None:
        """フォルダの作成・改名・削除と、登録件数の算出、他ユーザーからの遮断を検証する。"""

        WriteCaptureImage(self.upload_folder / 'a.jpg', BuildCaptureMetadata())
        WriteCaptureImage(self.upload_folder / 'b.jpg', BuildCaptureMetadata())

        async with self._client() as client:
            created = await client.post('/api/captures/folders', json={'name': '  お気に入り  '})
            self.assertEqual(created.status_code, 201, created.text)
            # 前後の空白は除去して保存する
            self.assertEqual(created.json()['name'], 'お気に入り')
            folder_id = created.json()['id']

            second = await client.post('/api/captures/folders', json={'name': 'あとで見る'})
            # 作成順に sort_order が採番される
            self.assertEqual([created.json()['sort_order'], second.json()['sort_order']], [0, 1])

            added = await client.post(
                f'/api/captures/folders/{folder_id}/captures',
                json={'filenames': ['a.jpg', 'b.jpg', 'a.jpg', 'missing.jpg']},
            )
            self.assertEqual(added.status_code, 204, added.text)
            # リクエスト内の重複と実ファイルの無い名前は登録されない
            self.assertEqual(await CaptureBookmark.filter(folder_id=folder_id).count(), 2)

            folder_captures = await client.get(f'/api/captures/folders/{folder_id}/captures')
            self.assertEqual(folder_captures.status_code, 200, folder_captures.text)
            self.assertEqual(folder_captures.json()['total'], 2)

            folders = await client.get('/api/captures/folders')
            self.assertEqual(folders.json()['total'], 2)
            self.assertEqual([folder['capture_count'] for folder in folders.json()['folders']], [2, 0])

            renamed = await client.put(f'/api/captures/folders/{folder_id}', json={'name': '推し'})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(renamed.json()['name'], '推し')
            self.assertEqual(renamed.json()['capture_count'], 2)

            # 空文字のフォルダ名は拒否する
            empty = await client.put(f'/api/captures/folders/{folder_id}', json={'name': '   '})
            self.assertEqual(empty.status_code, 422)

        # 他ユーザーのフォルダは存在を伏せて 404 を返す
        other_user = await User.create(name='other', password='x', is_admin=False)
        async with self._client(other_user) as client:
            hidden = await client.get(f'/api/captures/folders/{folder_id}/captures')
            self.assertEqual(hidden.status_code, 404)
            hidden_delete = await client.delete(f'/api/captures/folders/{folder_id}')
            self.assertEqual(hidden_delete.status_code, 404)

        # 本人が削除すると紐付いたブックマークも CASCADE で消える
        async with self._client() as client:
            deleted = await client.delete(f'/api/captures/folders/{folder_id}')
            self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(await CaptureBookmark.filter(folder_id=folder_id).count(), 0)
        # 実ファイルは残る
        self.assertTrue((self.upload_folder / 'a.jpg').is_file())

    async def test_folder_captures_skips_files_removed_from_disk(self) -> None:
        """フォルダ内一覧は、実ファイルが消えたブックマークを除外して返す。"""

        WriteCaptureImage(self.upload_folder / 'a.jpg', BuildCaptureMetadata())
        WriteCaptureImage(self.upload_folder / 'b.jpg', BuildCaptureMetadata())
        folder = await CaptureFolder.create(user=self.user, name='お気に入り')
        await CaptureBookmark.create(folder=folder, filename='a.jpg')
        await CaptureBookmark.create(folder=folder, filename='b.jpg')

        # サーバー PC 上で直接削除された状況を再現する
        (self.upload_folder / 'b.jpg').unlink()

        async with self._client() as client:
            response = await client.get(f'/api/captures/folders/{folder.id}/captures')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['total'], 1)
            self.assertEqual([c['filename'] for c in response.json()['captures']], ['a.jpg'])

            # 登録解除は実ファイルを消さない
            removed = await client.request(
                'DELETE',
                f'/api/captures/folders/{folder.id}/captures',
                json={'filenames': ['a.jpg']},
            )
            self.assertEqual(removed.status_code, 204, removed.text)
        # 解除したのは a.jpg のブックマークだけで、実ファイルが消えた b.jpg のブックマークは残る
        self.assertEqual(
            set(await CaptureBookmark.filter(folder=folder).values_list('filename', flat=True)),
            {'b.jpg'},
        )
        self.assertTrue((self.upload_folder / 'a.jpg').is_file())

    async def test_upload_saves_jpeg_and_rejects_non_image(self) -> None:
        """アップロード API が JPEG を保存し、画像以外を拒否する。"""

        buffer = io.BytesIO()
        Image.new('RGB', (64, 36), (0, 0, 0)).save(buffer, format='JPEG')

        async with self._client() as client:
            uploaded = await client.post(
                '/api/captures',
                files={'image': ('Capture_test.jpg', buffer.getvalue(), 'image/jpeg')},
            )
            self.assertEqual(uploaded.status_code, 204, uploaded.text)
            self.assertTrue((self.upload_folder / 'Capture_test.jpg').is_file())

            rejected = await client.post(
                '/api/captures',
                files={'image': ('evil.jpg', b'#!/bin/sh\necho hi\n', 'image/jpeg')},
            )
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(rejected.json()['detail'], 'Please upload JPEG or PNG image')
        self.assertEqual(CAPTURE_EXTENSIONS, {'.jpg', '.jpeg', '.png'})
