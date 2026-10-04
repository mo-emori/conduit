# conduit v0.1 設計書

**作成日:** 2026-10-05  
**Project:** `conduit`  
**Repository:** `C:\dev\conduit`  
**Development limit:** 3日以内

---

# 1. 目的

`conduit` は、ChatGPTからローカル実行環境上のActorへ開発作業を依頼し、その結果をChatGPTへ返すための小さな導管である。

v0.1の主要目的は、

> **Codexへ渡すコンテキスト量を必要十分な範囲まで減らしながら、ChatGPTからローカル開発作業を実行できることを確認する。**

同時に、CodexからChatGPTへ返す情報量も必要十分な範囲に抑える。

conduit自身を自律Agent、開発管理システム、信用管理システムにはしない。

---

# 2. v0.1完成条件

以下の1本の経路が実運用で成立すれば完成とする。

```text
ChatGPT
   ↓
Slack
   ↓
conduit
   ↓
Codex
   ↓
Local Workspace
   ↓
Codex Result
   ↓
conduit
   ↓
ChatGPT Web Callback
```

具体的には、

1. ChatGPTから開発instructionを送信できる
2. conduitがinstructionを受信できる
3. 指定workspaceでCodexを起動できる
4. Codexがworkspaceを自分で調査できる
5. Codexが作業を実行できる
6. 実行結果をconduitが取得できる
7. Codexの最終メッセージだけを指定ChatGPTチャットへcallbackできる

以上が成立すれば `v0.1 COMPLETE` とする。

---

# 3. 開発規模制約

## 3.1 3日制限

v0.1の開発期間は最大3日とする。

3日以内に必要性を確認できなかった機能はv0.1へ入れない。

## 3.2 大規模開発禁止

以下を禁止する。

- 将来拡張を理由とした抽象化
- 汎用framework化
- 大規模なclass hierarchy
- 複雑なprotocol
- 独自workflow engine
- 独自Agent framework
- 独自context engine
- 独自trust engine
- 過剰な永続化
- 想定上の障害への予防的機構
- 「後で必要になる」という理由だけの実装

原則：

> **実際に発生した問題だけ直す。**

---

# 4. 旧システムとの関係

旧 `chatgpt-agent` は破棄済みである。

旧実装・旧設計をconduitの設計Sourceとしない。

特に以下は引き継がない。

```text
Context Harness
hash management
provenance
trusted baseline
candidate
reconciliation
acceptance receipt
Trust Control Plane
migration
artifact lifecycle
旧protocol
旧test architecture
```

## 唯一のコード再利用例外

以下のみ旧コードの再利用を許可する。

> **ChatGPT Webブラウザへのcallback機構**

callback以外の旧コードは、新規実装より短くなるという理由だけでもコピーしない。

---

# 5. Integration Target

最初の実運用対象は、

```text
kairos
```

とする。

旧ARGUSは破棄済みであり、conduitの対象としない。

kairosはconduitの検証対象であって、conduit本体のドメインではない。

したがってconduit内部へ、

```text
KairosJob
KairosContext
KairosWorkflow
```

等のkairos固有概念を導入しない。

---

# 6. Actor

v0.1で対応するActorは、

```text
Codex
```

のみとする。

Claude Code対応はv0.1完成条件に含めない。

Codex経路が完成した後、追加が十分小さいと確認できた場合のみ別途検討する。

---

# 7. Context設計

## 7.1 基本方針

v0.1ではContext Harnessを作らない。

ChatGPTからCodexへ大量のファイル内容を転送しない。

基本入力は、

```text
workspace
instruction
```

とする。

必要なら少量の実行条件をinstructionへ含める。

## 7.2 双方向の情報量を抑える

削減対象はChatGPT → Codexだけではない。

```text
ChatGPT → Codex
Codex → ChatGPT
```

の両方向で、不要なコンテキスト投入を避ける。

Codexの探索ログや大量のstdoutをChatGPTへcallbackしない。

---

# 8. Context取得

Codexは対象workspaceへ配置する。

Codex自身がローカルworkspaceを探索し、

- ファイル検索
- ソースコード参照
- Git履歴確認
- テスト確認
- 必要箇所の読み込み

を行う。

したがって、

```text
ChatGPT
 ↓
大量context生成
 ↓
conduit
 ↓
Codex
```

ではなく、

```text
ChatGPT
 ↓
small instruction
 ↓
conduit
 ↓
Codex
 ↓
local workspace exploration
```

を基本モデルとする。

---

# 9. v0.1で検証する中心仮説

> **Codexを正しいworkspaceへ配置し、小さなinstructionだけを渡せば、Codex自身のローカル探索によって必要なcontextを取得できる。**

これが成立する場合、conduitに独自Context Harnessは不要と判断する。

成立しないケースが実運用で発生した場合、そのケースを観測してから対策を設計する。

---

# 10. conduitの責務

v0.1の責務を以下に限定する。

```text
Receive
Execute
Capture
Callback
```

### Receive

ChatGPTから送信されたJobを受信する。

`LOCAL-AGENT PING` を受信した場合は、

```text
LOCAL-AGENT PONG — Worker ready
```

を返す。

### Execute

指定workspaceでCodexを起動する。

### Capture

最低限、

```text
exit code
Codex final message
stdout
stderr
```

を取得する。

stdout / stderrはローカル診断用であり、通常のcallback本文には使用しない。

### Callback

Codexの最終メッセージを指定ChatGPTチャットへ返す。

---

# 11. conduitが判断しないもの

conduitは以下を判断しない。

- どのソースコードが重要か
- どのファイルを読むべきか
- 修正方法
- 設計判断
- コード品質
- テスト戦略
- commit可否
- 開発タスクの成功判定

これらはChatGPT、Codex、人間の責務とする。

conduitへ判断ロジックを重複実装しない。

---

# 12. 通信経路

v0.1では既に利用実績のあるSlackを利用する。

```text
Workspace:
ChatGPT Agent

Channel:
#codex-jobs
```

ChatGPTからSlackへJobを送信する前に必ず、

```text
LOCAL-AGENT PING
```

をplain textで送信する。

Workerから、

```text
LOCAL-AGENT PONG — Worker ready
```

を確認した後、Jobを送信する。

この手順は現在の実運用制約として扱う。

---

# 13. Callback

callback先：

```text
https://chatgpt.com/c/6ac26caf-b63c-83ec-83d0-9f8d926c3df7
```

Chat name:

```text
conduit
```

callback部分についてのみ旧 `chatgpt-agent` の実装を参照・再利用してよい。

callback内部の再設計はv0.1の目的ではない。

## Callbackする内容

通常callbackするのは、

> **Codexの最終メッセージのみ**

とする。

Codexの探索中stdout / stderr全体をChatGPTへcallbackしない。

Codex CLIが対応している場合、

```text
codex exec --output-last-message <file>
```

相当の機能を利用する。

実際のCLIオプションは実装時に、

```text
codex exec --help
```

で現在のCodex CLI仕様を確認する。

---

# 14. Job

v0.1ではJob構造を最小限とする。

```text
job_id
workspace
instruction
```

## workspace

外部からローカルパスを受け取らない。

Jobでは論理workspace名を使用する。

例：

```json
{
  "job_id": "conduit-test-001",
  "workspace": "kairos",
  "instruction": "README.mdを確認し、現在のプロジェクト構造を要約してください。ファイル変更は禁止します。"
}
```

conduit内部で、

```python
WORKSPACES = {
    "kairos": r"C:\dev\kairos",
    "conduit": r"C:\dev\conduit",
}
```

のようにローカルパスへ変換する。

登録されていないworkspace名は拒否する。

新しいJob fieldは実際に必要になるまで追加しない。

---

# 15. Result

結果は最小限とする。

内部では、

```text
job_id
exit_code
final_message
stdout
stderr
```

を取得できればよい。

## 正常終了時

ChatGPTへのcallbackは、

```text
job_id
final_message
```

を基本とする。

Codexの探索ログ、stdout、stderr全体をcallbackしない。

`final_message` はCodex CLIの最終メッセージ取得機能を利用して取得する。

## 異常終了時

Codex起動失敗、非zero exit等により正常な `final_message` を取得できない場合は、

```text
job_id
exit_code
stderr の末尾最大20行
```

をcallbackする。

これによりChatGPT側で最低限、

- どのJobが失敗したか
- 終了コード
- 直接のエラー内容

を確認できるようにする。

異常終了時にもstdout / stderr全体はcallbackしない。

`stderr` が存在しない場合は、取得できたエラー情報だけを返す。

## Callback自体が失敗した場合

ChatGPTへのcallbackそのものが失敗した場合は、ローカルconsoleへエラーを出力する。

v0.1では、

```text
automatic retry
callback queue
failed callback persistence
reconciliation
```

等は実装しない。

高度なresult schemaも作らない。

---

# 16. 実行方式

v0.1は、

> **1 Jobずつ逐次実行**

とする。

並列実行しない。

以下を作らない。

```text
job queue
parallel worker
scheduler
worker pool
priority control
```

必要性が実運用で発生するまで検討しない。

---

# 17. State

conduitは原則statelessとする。

DBは導入しない。

以下もv0.1では作らない。

```text
SQLite
job database
history database
context database
baseline database
artifact database
```

実行中Jobを処理するため最低限必要な一時状態だけ保持する。

---

# 18. Git / Commit運用

Codexによる変更後、ChatGPTが内容を確認する。

コミット可能と判断した場合、ChatGPTは明示的に、

```text
コミットしてよい
```

と伝える。

同時にcommit message案を提示する。

例：

```text
コミットしてよい

Commit message:
feat: add minimal conduit worker
```

## Commit実行

commit専用機構は作らない。

commitはCodexへ送る通常Jobとして実行する。

例：

```text
現在の変更を以下のmessageでcommitしてください。

feat: add minimal conduit worker
```

commit完了後、そのcommitを次Jobのbaselineとして扱う。

baseline管理機構をconduit内部には作らない。

> **Git自身をbaselineとする。**

---

# 19. 想定ファイル構成

初期段階では最小構成を優先する。

例：

```text
C:\dev\conduit
│
├─ .venv\
├─ .gitignore
├─ README.md
├─ conduit.py
└─ callback.py
```

必要性が発生するまで、

```text
src/
core/
domain/
services/
adapters/
interfaces/
infrastructure/
```

等へ分割しない。

1ファイルが読みにくくなった時点で初めて分割する。

---

# 20. Python環境

現在の環境：

```text
Python 3.14.7
pip 26.2.1

venv:
C:\dev\conduit\.venv
```

依存パッケージは設計上必要になったものだけ追加する。

「一般的に使う」という理由でpackageを追加しない。

Python標準ライブラリで十分な処理は標準ライブラリを使用する。

---

# 21. Windows実装条件

Windows上での最小実装では以下を確認する。

## Codex executable

npm版Codex等で実体が `codex.cmd` となる場合を考慮し、

```python
shutil.which("codex")
```

等で実行ファイルを解決する。

## Encoding

subprocess出力では必要に応じて、

```python
encoding="utf-8"
errors="replace"
```

を指定する。

Windowsのデフォルトencodingへ暗黙依存しない。

## Instruction

長い日本語instructionをargvへ直接展開せず、Codex CLIが対応している場合はstdinを使用する。

概念例：

```text
codex exec -
```

## Workspace

Codex CLIのworkspace指定機能を利用する。

Jobから受け取った論理workspace名を `WORKSPACES` でローカルパスへ解決し、そのworkspaceでCodexを実行する。

## Sandbox

v0.1では全Jobについて一律、

```text
workspace-write
```

を使用する。

conduitはinstructionの内容を解釈してsandboxを選択しない。

読み取り専用として実行したいJobについては、

```text
ファイルを変更しないこと。
```

等をinstructionとしてCodexへ伝える。

`read-only` の強制が実運用上必要になった場合、その事実を確認してから `mode` 等のJob field追加を検討する。

v0.1ではsandbox選択機構を作らない。

OSおよびCodexが提供する既存sandbox機能を使用し、独自sandboxを実装しない。

実際のCLIフラグ名および挙動は、実装開始時に、

```text
codex exec --help
```

で使用中のCodex CLIについて確認する。

---

# 22. エラー処理

v0.1では高度なrecovery機構を作らない。

最低限、

- Codexを起動できなかった
- workspaceが存在しない
- Codexが非zero exit
- callbackに失敗した

ことが分かればよい。

自動retry、reconciliation、rollback等は導入しない。

## Timeout

Codexのハングが実際に発生した場合、

```python
subprocess.run(..., timeout=...)
```

等の既存機能で対応する。

独自timeout管理機構は作らない。

E2E実行前に単純なtimeout指定を入れることが実装上自然であれば、それを妨げない。

---

# 23. Security

v0.1では独自security frameworkを作らない。

Actorが操作できるworkspaceは、

```text
WORKSPACES
```

に登録されたものへ限定する。

conduit自身が新しいtrust modelを構築することは禁止する。

OS、Git、Codex、Slack等の既存境界を利用する。

---

# 24. テスト

巨大なtest suiteを作らない。

最初に必要なのはEnd-to-End確認である。

## E2E-001 — 基本経路

```text
ChatGPT
→ Slack
→ conduit
→ Codex
→ kairos
→ conduit
→ ChatGPT callback
```

を通す。

確認項目：

- `LOCAL-AGENT PING` に応答できる
- Jobを受信できる
- workspace名 `kairos` をローカルworkspaceへ解決できる
- Codexを起動できる
- Codexがローカルworkspaceを探索できる
- Codexの最終メッセージを取得できる
- 最終メッセージだけをChatGPTへcallbackできる

## E2E-002 — 実開発Job

kairosに対する実際の小規模開発Jobを1件実行する。

ここで、

- instruction量
- Actor入力token
- callback量
- 実行結果
- Actorが必要ファイルを自力発見できたか

を確認する。

---

# 25. Token評価

conduitの存在理由に直接関係するため、token量は実測する。

評価対象は、

```text
ChatGPT → Codex input
Codex → ChatGPT callback
```

の両方向とする。

Codex CLIが終了時にusageを表示する場合は、その値を利用する。

`--json` 等でusageイベントを取得できる場合も、既存出力を利用する。

usage取得のための独自計測frameworkは作らない。

旧方式との厳密なbenchmark frameworkも作らない。

まず実運用Jobについて、

```text
大量context投入
大量stdout callback
```

の双方が消えていることを確認する。

---

# 26. 開発順序

## Step 1

Python環境構築。

**完了済み。**

## Step 2

本設計書を確定。

## Step 3

最小conduit workerを作る。

この段階で、

```text
LOCAL-AGENT PING
→
LOCAL-AGENT PONG — Worker ready
```

も処理できるようにする。

## Step 4

Codexを起動できるようにする。

実装前に、

```text
codex exec --help
```

で現行CLI仕様を確認する。

## Step 5

旧コードからChatGPT callback部分だけ取り出す。

## Step 6

Codex最終メッセージだけをcallbackできるようにする。

## Step 7

E2E-001を実行する。

## Step 8

kairosで実Jobを1件実行する。

## Step 9

token消費と不足機能を観測する。

## Step 10

観測された致命的問題だけ修正する。

## Step 11

`conduit v0.1 COMPLETE`

---


# 27. v0.1非対象

以下は明示的にv0.1対象外とする。

```text
Claude Code
multi-agent
agent orchestration
context harness
RAG
vector database
knowledge graph
automatic context selection engine
trust management
provenance management
hash validation
artifact lifecycle
workflow engine
Web UI
management dashboard
distributed execution
cloud execution
job scheduler
job queue
parallel execution
worker pool
autonomous planning
automatic commit
automatic merge
large-scale test framework
plugin architecture
general-purpose SDK
```

これらが将来有用である可能性は、v0.1へ導入する理由としない。

実運用で必要性が発生した場合のみ、その時点で検討する。

---

# 28. 設計判断基準

機能追加を提案するときは、最初に以下を問う。

> **これがなければv0.1のE2Eが成立しないか？**

答えがNOなら実装しない。

次に、

> **実際のconduit運用で既に発生した問題を解決するものか？**

答えがNOなら原則として実装しない。

さらに、

> **3日以内の完成を危険にするか？**

YESなら削除する。

設計上の予測より、実際の運用結果を優先する。

---

# 29. 肥大化防止原則

conduitの規模が増え始めた場合、新しい機構を追加する前に、

> **その処理をChatGPT、Codex、Git、OS、Slack等の既存機能へ任せられないか**

を確認する。

任せられる場合、conduitには実装しない。

特に、

```text
判断
計画
Context探索
コード理解
Git履歴管理
sandbox
commit
品質評価
```

について、既存Actor・既存ツールと同じ機能をconduitへ再実装しない。

conduitはActorを制御する巨大なシステムではない。

---

# 30. conduit v0.1の定義

conduit v0.1は、

> **ChatGPTから小さなinstructionを受け取り、指定されたローカルworkspaceでCodexを実行し、その最終結果をChatGPTへ返す小さなPythonプログラム**

である。

主要なデータフローは、

```text
ChatGPT
   │
   │ small instruction
   ▼
Slack
   │
   ▼
conduit
   │
   │ workspace name
   │ instruction
   ▼
Codex
   │
   │ local workspace exploration
   ▼
Local Workspace
   │
   ▼
Codex final message
   │
   ▼
conduit
   │
   ▼
ChatGPT Web Callback
```

とする。

conduitは、この経路を成立させる以上の役割を持たない。

---

# 31. 成功判定

以下の条件を満たした時点でv0.1開発を停止する。

### Functional

実際のkairos開発Jobについて、

```text
ChatGPT
→ Slack
→ conduit
→ Codex
→ kairos
→ conduit
→ ChatGPT
```

がEnd-to-Endで成立する。

### Context

ChatGPTからCodexへ大量のプロジェクトcontextを事前投入しなくても、Codexがローカルworkspaceを探索してJobを実行できる。

### Callback

Codexの探索ログ全体ではなく、原則として最終メッセージだけがChatGPTへ返る。

### Token

Actorへの大量context投入と、ChatGPTへの大量stdout callbackの双方が発生していないことを実測・確認する。

### Development Size

3日以内に完成する。

---

# 32. v0.1完成後

成功条件を満たしたら、

```text
conduit v0.1 COMPLETE
```

とする。

その時点で新機能追加を続けない。

conduitをkairos開発へ実投入し、実際のJobを流す。

その運用中に問題が発生した場合、

```text
問題発生
↓
事実確認
↓
既存機能で解決できるか確認
↓
できなければ最小修正
```

の順で対応する。

将来機能のロードマップを理由としてv0.1を拡張しない。

---

# 33. 最終原則

conduitの価値は機能数ではない。

> **ChatGPTとローカルActorの間を、少ないコンテキストと少ないコードで接続できること**

を価値とする。

複雑な制御が必要になった場合も、それがconduit自身の責務であることを実運用から確認してから追加する。

**小さい状態で動けば、それを完成とする。**