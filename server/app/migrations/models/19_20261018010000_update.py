from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Annict 連携の公開プロフィールと暗号化済みトークン
        ALTER TABLE "users" ADD COLUMN "annict_user_id" INT;
        ALTER TABLE "users" ADD COLUMN "annict_user_name" TEXT;
        ALTER TABLE "users" ADD COLUMN "annict_user_nickname" TEXT;
        ALTER TABLE "users" ADD COLUMN "annict_user_avatar_url" TEXT;
        ALTER TABLE "users" ADD COLUMN "annict_access_token" TEXT;
        -- 視聴記録の自動投稿 (既定は無効)
        ALTER TABLE "users" ADD COLUMN "annict_auto_record_playback" INT NOT NULL DEFAULT 0;

        -- 照合済みの Annict 作品情報
        ALTER TABLE "series" ADD COLUMN "annict_work_id" INT;
        ALTER TABLE "series" ADD COLUMN "annict_work_name" TEXT;
        -- 同じ Annict 作品へ複数の Series が紐付かないようにする
        CREATE UNIQUE INDEX IF NOT EXISTS "series_annict_work_id" ON "series" ("annict_work_id");

        -- Annict へ投稿した視聴記録の台帳
        CREATE TABLE IF NOT EXISTS "annict_episode_records" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            "annict_episode_id" INT NOT NULL,
            "annict_record_id" INT NOT NULL,
            "recorded_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "source_recorded_program_id" INT REFERENCES "recorded_programs" ("id") ON DELETE SET NULL
        );
        -- 同じエピソードを同じユーザーが二重に記録しないためのユニーク制約
        CREATE UNIQUE INDEX IF NOT EXISTS "annict_episode_records_user_episode"
            ON "annict_episode_records" ("user_id", "annict_episode_id");
        -- 録画単位の追跡と、録画削除時の SET NULL を高速化する
        CREATE INDEX IF NOT EXISTS "annict_episode_records_source"
            ON "annict_episode_records" ("source_recorded_program_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "annict_episode_records_source";
        DROP INDEX IF EXISTS "annict_episode_records_user_episode";
        DROP TABLE IF EXISTS "annict_episode_records";
        DROP INDEX IF EXISTS "series_annict_work_id";
        ALTER TABLE "series" DROP COLUMN "annict_work_name";
        ALTER TABLE "series" DROP COLUMN "annict_work_id";
        ALTER TABLE "users" DROP COLUMN "annict_auto_record_playback";
        ALTER TABLE "users" DROP COLUMN "annict_access_token";
        ALTER TABLE "users" DROP COLUMN "annict_user_avatar_url";
        ALTER TABLE "users" DROP COLUMN "annict_user_nickname";
        ALTER TABLE "users" DROP COLUMN "annict_user_name";
        ALTER TABLE "users" DROP COLUMN "annict_user_id";
    """
