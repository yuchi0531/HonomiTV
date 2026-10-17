# 録画完了通知の Webhook 対応

## 契約

- `notifications.services[]` の `type` に `'Webhook'` を追加した。`webhook_url` に Discord の Incoming Webhook URL を設定すると、録画完了時に Embed 形式の JSON を POST する。既存の `'Telegram'` / `'Slack'` の扱いは変更しない。
- サービスは `type` で選択する。`enabled: true` でも必須項目 (`Webhook` なら `webhook_url`、`Telegram` なら `bot_token` と `chat_id`) が空の場合はサービスとして組み立てず、警告ログだけを残す (既存 Telegram と同じ挙動)。
- Webhook URL は前後の空白を除去してから使う。コピー & ペーストで混入する改行・空白でリクエストが壊れるのを防ぐため。
- 送信内容は Discord の Webhook が受理する `embeds` 形式。`content` は使わず、`allowed_mentions.parse` を空にしてメンションを発生させない。
- サムネイルが存在する場合は `multipart/form-data` で `payload_json` + `files[0]` として添付し、Embed の `image.url` を `attachment://thumbnail.webp` で参照する。存在しない場合は `application/json` で送る。
- Discord の Embed 上限 (description 4096 / title 256 / field value 1024 / footer 2048 / fields 25 / 合計 6000 文字) を超えると 400 で拒否されるため、送信前に切り詰める。番組名と概要は結合したうえで description の上限に収め、視聴リンクはフィールド数と合計文字数の両方の上限に収まるよう後ろから間引く。通知の要であるチャンネル・放送時間・長さの 3 フィールドは常に残す。
- 視聴リンクは録画 ID が確定している (`id >= 0`) 場合のみ生成する。DB 保存前の一時オブジェクトでは開けないリンクを通知しない。
- 送信失敗時は例外を送出する。`NotificationManager.send_new_recording()` は全サービスへの送信を試行したうえでエラーをログに記録し、`send_test()` は最初のエラーを呼び出し元へ返す (既存挙動を踏襲)。
- 設定画面では、有効な通知サービスの必須項目が空の場合に保存前のエラーを表示する。サーバー側が黙って通知を止める状態のまま保存されるのを避けるため。

## 検証

- サーバー: `server/tests/test_notification_service.py` で 18 件。Embed の内容 (タイトル・色・footer・フィールド)、視聴リンクの生成条件、長い本文・タイトル・チャンネル名の切り詰め、フィールド数と合計文字数の上限、サムネイル添付時の multipart 形式、サムネイル欠落時の JSON フォールバック、テスト通知のタイトル、URL 未設定時の失敗、HTTP エラーの伝播、`NotificationManager` の組み立て (有効/無効・URL 未設定) と並列送信・テスト通知のエラー伝播を検証する。
- モックだけでなく、ローカルの HTTP サーバーに対して実際に送信し、`application/json` の JSON 構造と、`multipart/form-data` の `payload_json` / `files[0]` / WebP バイト列が期待どおりの形で送られることを確認した。
- 既存設定の後方互換性 (`type` 未指定は Telegram、旧 Telegram 設定の読み込み、`Slack` の型が残ること) を確認した。
- 実際の Discord チャンネルへの到達確認は、Webhook URL を用意できる環境でのみ可能。ユーザー管理のサーバーを無断で起動・再起動しない。
