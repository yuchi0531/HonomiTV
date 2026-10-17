# Type Hints を指定できるように
# ref: https://stackoverflow.com/a/33533514/17124142
from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model as TortoiseModel


if TYPE_CHECKING:
    from app.models.CaptureFolder import CaptureFolder


class CaptureBookmark(TortoiseModel):
    """
    キャプチャフォルダとキャプチャ画像の紐付けを管理する中間テーブル。
    キャプチャ画像はファイルシステム上にあり DB にレコードを持たないため、
    外部キーの代わりにファイル名 (filename) で画像を識別する。
    """

    # データベース上のテーブル名
    class Meta(TortoiseModel.Meta):
        table: str = 'capture_bookmarks'
        # 同一フォルダ内に同じファイル名を二重登録しないためのユニーク制約
        unique_together = (('folder', 'filename'),)

    # ブックマーク ID (自動採番)
    id = fields.IntField(pk=True)
    # 所属先のフォルダ
    ## フォルダ削除時にブックマークも連動して削除する
    folder: fields.ForeignKeyRelation[CaptureFolder] = \
        fields.ForeignKeyField('models.CaptureFolder', related_name='bookmarks', on_delete=fields.CASCADE)
    folder_id: int
    # キャプチャ画像のファイル名 (拡張子を含む)
    ## 実ファイルが後から削除された場合に備え、参照時は必ず実ファイルの存在を確認する
    filename = fields.TextField()
    # フォルダへの追加日時
    created_at = fields.DatetimeField(auto_now_add=True)
