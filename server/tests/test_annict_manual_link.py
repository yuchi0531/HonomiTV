import unittest
from typing import cast
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import Tortoise

from app.constants import DATABASE_CONFIG
from app.models.Series import Series
from app.models.User import User
from app.routers.AnnictRouter import router


def BuildApp(user: User) -> FastAPI:
    """
    認証済みユーザーを固定したテスト用アプリを組み立てる。

    Args:
        user (User): 認証済みとして扱うユーザー。

    Returns:
        FastAPI: テスト用アプリ。
    """

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[__import__(
        'app.routers.UsersRouter', fromlist = ['GetCurrentUser'],
    ).GetCurrentUser] = lambda: user
    return app


class AnnictManualLinkTest(unittest.IsolatedAsyncioTestCase):
    """Annict 作品の手動紐づけを検証する。"""

    async def asyncSetUp(self) -> None:
        """テスト専用のメモリ内 SQLite とユーザーを用意する。"""

        await Tortoise.init(
            db_url = 'sqlite://:memory:',
            modules = {'models': cast(list[str], DATABASE_CONFIG['apps']['models']['models'])},
        )
        await Tortoise.generate_schemas()

        self.user = await User.create(name='annict-user', password='x', is_admin=False)
        self.user.annict_user_id = 1
        self.user.annict_user_name = 'viewer'
        self.user.annict_access_token = self.user.encryptAnnictAccessToken('token')
        await self.user.save(update_fields=['annict_user_id', 'annict_user_name', 'annict_access_token'])
        self.app = BuildApp(self.user)

    async def asyncTearDown(self) -> None:
        """メモリ内 SQLite 接続を破棄する。"""

        await Tortoise.close_connections()

    async def test_lists_unlinked_series(self) -> None:
        """未紐づけのシリーズだけを一覧へ返す。"""

        await Series.create(
            normalized_title='linked', title='紐づけ済み', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
            annict_work_id=100, annict_work_name='紐づけ済み',
        )
        await Series.create(
            normalized_title='unlinked', title='未紐づけ', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
        )
        # 対象外ジャンルは一覧へ出さない
        await Series.create(
            normalized_title='sports', title='スポーツ番組', description='',
            genres=[{'major': 'スポーツ', 'middle': ''}],
        )

        with TestClient(self.app) as client:
            response = client.get('/api/annict/unlinked-series')

        self.assertEqual(response.status_code, 200)
        titles = [item['title'] for item in response.json()['series_list']]
        self.assertEqual(titles, ['未紐づけ'])

    async def test_searches_annict_works_by_title(self) -> None:
        """タイトルで Annict 作品を検索できる。"""

        works = [
            {'id': 7777, 'titles': ['ゆるキャン△', 'Yuru Camp', 'ゆるきゃん']},
        ]
        with (
            patch('app.routers.AnnictRouter.AnnictClient.searchWorksByTitle', AsyncMock(return_value=works)),
            TestClient(self.app) as client,
        ):
            response = client.get('/api/annict/works/search', params={'query': 'ゆるキャン'})

        self.assertEqual(response.status_code, 200)
        work = response.json()['works'][0]
        self.assertEqual(work['id'], 7777)
        self.assertEqual(work['title'], 'ゆるキャン△')
        self.assertEqual(work['title_en'], 'Yuru Camp')
        self.assertEqual(work['title_kana'], 'ゆるきゃん')

    async def test_links_series_to_annict_work(self) -> None:
        """指定した Annict 作品へシリーズを紐づける。"""

        series = await Series.create(
            normalized_title='target', title='対象作品', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
        )
        works = [{'id': 8888, 'titles': ['対象作品']}]

        with (
            patch('app.routers.AnnictRouter.AnnictClient.searchWorksByTitle', AsyncMock(return_value=works)),
            TestClient(self.app) as client,
        ):
            response = client.put(
                f'/api/annict/series/{series.id}/link',
                json={'annict_work_id': 8888},
            )

        self.assertEqual(response.status_code, 204)
        refreshed = await Series.get(id=series.id)
        self.assertEqual(refreshed.annict_work_id, 8888)
        self.assertEqual(refreshed.annict_work_name, '対象作品')

    async def test_rejects_work_already_linked_to_another_series(self) -> None:
        """既に別のシリーズへ紐づいている作品は拒否する。"""

        await Series.create(
            normalized_title='first', title='先に紐づけた作品', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
            annict_work_id=9999, annict_work_name='先に紐づけた作品',
        )
        series = await Series.create(
            normalized_title='second', title='別の作品', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
        )

        with TestClient(self.app) as client:
            response = client.put(
                f'/api/annict/series/{series.id}/link',
                json={'annict_work_id': 9999},
            )

        self.assertEqual(response.status_code, 422)
        refreshed = await Series.get(id=series.id)
        self.assertIsNone(refreshed.annict_work_id)

    async def test_link_succeeds_even_when_title_lookup_fails(self) -> None:
        """作品名を取得できなくても、ID だけで紐づけは成立する。"""

        series = await Series.create(
            normalized_title='fallback', title='作品名不明', description='',
            genres=[{'major': 'アニメ・特撮', 'middle': '国内アニメ'}],
        )
        with (
            patch(
                'app.routers.AnnictRouter.AnnictClient.searchWorksByTitle',
                AsyncMock(side_effect = httpx.ConnectError('boom')),
            ),
            TestClient(self.app) as client,
        ):
            response = client.put(
                f'/api/annict/series/{series.id}/link',
                json={'annict_work_id': 5555},
            )

        self.assertEqual(response.status_code, 204)
        refreshed = await Series.get(id=series.id)
        self.assertEqual(refreshed.annict_work_id, 5555)
        # 作品名は Series のタイトルで補う
        self.assertEqual(refreshed.annict_work_name, '作品名不明')
