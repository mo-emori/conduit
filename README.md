# conduit

Slack から Job を受け取り、指定 workspace で Codex CLI を実行する v0.1 の最小 Worker です。

## セットアップと実行

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SLACK_BOT_TOKEN = "xoxb-..."
$env:SLACK_APP_TOKEN = "xapp-..."
$env:SLACK_CHANNEL_ID = "C0123456789" # #codex-jobs の channel ID
.venv\Scripts\python.exe conduit.py
```

Slack App では Socket Mode を有効にし、`app_token` に `connections:write`、Bot に
`channels:history`、`chat:write`（private channel なら `groups:history` も）を付与して、
対象 channel に Bot を参加させます。

疎通確認は `LOCAL-AGENT PING`、Job は次の JSON を1メッセージで送信します。

```json
{
  "job_id": "example-001",
  "workspace": "kairos",
  "instruction": "README.mdを確認し、プロジェクト構成を要約してください。ファイルは変更しないでください。"
}
```

Job は逐次実行され、返信は元メッセージの thread に投稿されます。

ChatGPT Web callbackには、Chromeをremote debugging port `9222`で起動し、ログイン済みの
Chromeで固定callback先のチャットを1タブだけ開いておく必要があります。
