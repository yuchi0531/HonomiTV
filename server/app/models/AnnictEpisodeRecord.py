# Type Hints を指定できるように
# ref: https://stackoverflow.com/a/33533514/17124142
from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model as TortoiseModel


if TYPE_CHECKING:
    from app.models.RecordedProgram import RecordedProgram
    from app.models.User import User


class AnnictEpisodeRecord(TortoiseModel):
    """
    Annict へ投稿した視聴記録 (record) を、ユーザーとエピソード単位で保持する。

    Annict の record は公開の視聴ログになるため、同じエピソードを重複投稿しないための台帳として使う。
    """

    # データベース上のテーブル名
    class Meta(TortoiseModel.Meta):
        table: str = 'annict_episode_records'
        # 同じエピソードを同じユーザーが二重に記録しないためのユニーク制約
        unique_together = (('user', 'annict_episode_id'),)

    id = fields.IntField(pk=True)
    # 記録を投稿した KonomiTV ユーザー
    user: fields.ForeignKeyRelation[User] = \
        fields.ForeignKeyField('models.User', related_name=None, on_delete=fields.CASCADE)
    user_id: int
    # Annict のエピソード ID
    annict_episode_id = fields.IntField()
    # Annict 側の record ID (投稿に成功した場合のみ)
    ## 将来 record の削除や編集を行う場合に、対象を特定するために保持する
    annict_record_id = fields.IntField()
    # どの録画で視聴完了になったかを追跡できるよう、同期元の録画を保持する
    source_recorded_program: fields.ForeignKeyNullableRelation[RecordedProgram] = \
        fields.ForeignKeyField('models.RecordedProgram', related_name=None, null=True, on_delete=fields.SET_NULL)
    source_recorded_program_id: int | None
    recorded_at = fields.DatetimeField(auto_now_add=True)
