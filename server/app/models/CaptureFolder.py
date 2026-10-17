# Type Hints を指定できるように
# ref: https://stackoverflow.com/a/33533514/17124142
from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model as TortoiseModel


if TYPE_CHECKING:
    from app.models.CaptureBookmark import CaptureBookmark
    from app.models.User import User


class CaptureFolder(TortoiseModel):
    """
    キャプチャフォルダを管理するモデル。
    ユーザーが手動作成する仮想フォルダで、実ファイルの移動は一切行わない。
    フォルダとキャプチャ画像の紐付けは中間テーブル CaptureBookmark で管理する。
    """

    # データベース上のテーブル名
    class Meta(TortoiseModel.Meta):
        table: str = 'capture_folders'

    # フォルダ ID (自動採番)
    id = fields.IntField(pk=True)
    # フォルダを所有するユーザー
    ## キャプチャフォルダはユーザーごとの私的な整理棚なので、ユーザー削除時にフォルダごと削除する
    user: fields.ForeignKeyRelation[User] = \
        fields.ForeignKeyField('models.User', related_name='capture_folders', on_delete=fields.CASCADE)
    user_id: int
    # フォルダ名 (ユーザーが自由に命名する)
    name = fields.TextField()
    # フォルダの表示順序 (小さい値ほど先頭に表示する)
    ## 現状は作成順に採番するだけで並べ替え UI は無いが、将来のドラッグ & ドロップ並べ替えのために保持する
    sort_order = fields.IntField(default=0)
    # このフォルダに紐付けられたキャプチャ (逆参照)
    bookmarks: fields.ReverseRelation[CaptureBookmark]
    # 作成日時・更新日時
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
