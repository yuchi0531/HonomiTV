from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- キャプチャフォルダ (ユーザーごとの仮想フォルダ)
        CREATE TABLE IF NOT EXISTS "capture_folders" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            "name" TEXT NOT NULL,
            "sort_order" INT NOT NULL DEFAULT 0,
            "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
        );
        -- キャプチャフォルダとキャプチャ画像 (ファイル名) の紐付け
        CREATE TABLE IF NOT EXISTS "capture_bookmarks" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            "filename" TEXT NOT NULL,
            "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "folder_id" INT NOT NULL REFERENCES "capture_folders" ("id") ON DELETE CASCADE
        );
        -- 同一フォルダ内で同じファイル名を二重登録しないためのユニーク制約
        CREATE UNIQUE INDEX IF NOT EXISTS "capture_bookmarks_folder_filename"
            ON "capture_bookmarks" ("folder_id", "filename");
        -- ユーザーごとのフォルダ一覧取得を高速化する
        CREATE INDEX IF NOT EXISTS "capture_folders_user_id" ON "capture_folders" ("user_id");
        -- キャプチャ削除時のブックマーク掃除とファイル名検索を高速化する
        CREATE INDEX IF NOT EXISTS "capture_bookmarks_filename" ON "capture_bookmarks" ("filename");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "capture_bookmarks_filename";
        DROP INDEX IF EXISTS "capture_folders_user_id";
        DROP INDEX IF EXISTS "capture_bookmarks_folder_filename";
        DROP TABLE IF EXISTS "capture_bookmarks";
        DROP TABLE IF EXISTS "capture_folders";
    """
