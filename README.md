# conduit

v0.3 adds an explicit Google Drive upload operation while preserving the v0.2 Codex Job contract.

Configure the existing `My Drive/chatgpt/jobs` folder ID and external OAuth files in `config.toml`:

```toml
[drive]
jobs_folder_id = "REPLACE_WITH_GOOGLE_DRIVE_JOBS_FOLDER_ID"
credentials_file = "C:/Users/mttge/AppData/Roaming/conduit/credentials.json"
token_file = "C:/Users/mttge/AppData/Roaming/conduit/token.json"
```

An upload message is a separate strict JSON object:

```json
{
  "operation": "upload",
  "job_id": "example-001",
  "workspace": "kairos",
  "paths": ["main.py", "tests/test_llm.py"]
}
```

As with Codex Jobs, the sender must JSON-serialize and Slack-send this object in one programmatic tool execution; do not compose escaped JSON manually.

Slack から Job を受け取り、指定 workspace で Codex CLI を実行する v0.2 の最小 Worker です。

## セットアップと実行

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
python conduit.py
```

`config.toml` は workspace ごとのローカルパスと ChatGPT Web callback 先を管理します。
workspace を追加するときは `path` と `callback_url` の2項目だけを設定してください。

```toml
[workspaces.conduit]
path = "C:\\dev\\conduit"
callback_url = "https://chatgpt.com/c/6ac26caf-b63c-83ec-83d0-9f8d926c3df7"

[workspaces.kairos]
path = "C:\\dev\\kairos"
callback_url = "https://chatgpt.com/c/6ac26c6e-9710-83ee-b641-9f17d64cd7a9"
```

`.env` は従来どおり Slack の secret / local settings 専用です。

起動前にrepository rootの `.env` へ `SLACK_BOT_TOKEN`、`SLACK_APP_TOKEN`、
`SLACK_CHANNEL_ID` を設定してください。`.env` は秘密値を含むためGitへcommitしません。

Slack App では Socket Mode を有効にし、`app_token` に `connections:write`、Bot に
`channels:history`、`chat:write`（private channel なら `groups:history` も）を付与して、
対象 channel に Bot を参加させます。

疎通確認は `LOCAL-AGENT PING`、Job は次のJSONを1メッセージで送信します。

```json
{
  "job_id": "example-001",
  "workspace": "kairos",
  "instruction_base64": "<UTF-8 instruction encoded as Base64>"
}
```

`instruction_base64` はsender側の同一tool execution内で、元instructionをUTF-8、
Base64、JSONの順に機械的に変換して生成してください。Base64 payloadを手作業で
作成したり、LLMが生成したBase64文字列をコピーしたりしないでください。

Job は逐次実行され、返信は元メッセージの thread に投稿されます。

ChatGPT Web callbackには、Chromeをremote debugging port `9222`で起動し、ログイン済みの
ChromeでJobのworkspaceに設定したcallback先のチャットを1タブだけ開いておく必要があります。

実行ログは標準出力と `logs/conduit.log` に出力されます。ログファイルは最大10MB、
10世代保持です。
