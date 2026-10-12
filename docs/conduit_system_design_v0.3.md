# conduit System Design v0.3

**Date:** 2026-10-06  
**Project:** `conduit`

## 1. Purpose and boundary

`conduit` is a small conduit between ChatGPT and local Codex execution. It is not an autonomous agent, workflow engine, trust system, context harness, or artifact-management system.

The proven v0.2 path is the baseline:

```text
ChatGPT -> Slack -> conduit -> Codex -> local workspace
        -> final result -> workspace-specific ChatGPT callback
```

v0.3 adds one narrow capability: after implementation or review, explicitly selected local files can be uploaded to Google Drive. This is a separate operation, not automatic behavior of every Codex Job.

## 2. Proven v0.2 baseline

The following behavior is implemented and has already been proven:

- Codex is the only execution actor.
- `conduit` processes one Job at a time. It has no queue, scheduler, worker pool, or parallel Job execution.
- ChatGPT sends a small instruction; Codex explores the selected local workspace for the context it needs.
- ChatGPT performs `LOCAL-AGENT PING` / `LOCAL-AGENT PONG — Worker ready` before sending a Job.
- Logical workspace names and workspace-specific ChatGPT callback destinations are configured in `config.toml`.
- A Job is one JSON object containing exactly `job_id`, `workspace`, and `instruction_base64`.
- The sender mechanically performs instruction UTF-8 encoding, Base64 encoding, JSON serialization, and Slack send in one tool execution. LLM-generated or manually composed Base64, and copying Base64 between steps, are prohibited.
- The callback sends the Codex final message, not exploration logs.
- Codex stdout and stderr are logged locally in real time for diagnosis.
- The conduit virtual environment is removed from each Job environment. `VIRTUAL_ENV`, `PYTHONPATH`, and `PYTHONHOME` are removed, while configured `job_path_prepend` entries are retained.
- Each Job receives a workspace-local `.conduit-tmp/job-<random>` directory through `TMPDIR`; that directory is cleaned after the Job.
- A Git commit is the development baseline. `conduit` does not implement baseline management.

These are historical v0.2 baseline claims, retained for the already tagged v0.3.0. The proposed v0.3.x wire revision in Section 4 changes the Job fields; Drive upload remains a separate, explicit operation.

## 3. v0.3 scope: explicit Drive artifact upload

After implementation or review is complete, ChatGPT or a human may explicitly select workspace-relative file paths for upload. `conduit` uploads those files sequentially to:

```text
My Drive/chatgpt/jobs/<job_id>/
```

There is no `artifacts` subfolder.

For a KAIROS end-to-end run, the explicitly selected paths are:

```text
config.json
main.py
llm.py
risk.py
report.py
tests/test_llm.py
tests/test_risk.py
tests/test_vertical_slice.py
```

`conduit` must not infer artifact paths from Codex final prose, a Git diff, repository scanning, or any automatic artifact-discovery process. ChatGPT or a human supplies the complete path selection explicitly.

## 4. Proposed v0.3.x routing and wire revision

This is a compatibility-breaking proposal for review in ChatGPT before implementation, distinct from the behavior already tagged v0.3.0. `workspace` selects the local execution root; `sender` selects the registered ChatGPT callback destination. They are independent: `workspace=kairos, sender=conduit` executes in `C:/dev/kairos` and returns to the conduit chat.

`config.toml` separates the two registrations:

```toml
[workspaces.conduit]
path = "C:/dev/conduit"

[workspaces.kairos]
path = "C:/dev/kairos"

[senders.conduit]
callback_url = "https://chatgpt.com/c/6ac26caf-b63c-83ec-83d0-9f8d926c3df7"

[senders.kairos]
callback_url = "https://chatgpt.com/c/6acaae4a-3010-83ec-8cfe-d1a773081a3c"
```

Each `[workspaces.<name>]` contains only the local execution path. Each `[senders.<name>]` contains the callback URL for a registered ChatGPT chat. Both Codex and Upload callbacks use `SENDERS[sender].callback_url`, never `WORKSPACES[workspace].callback_url`. The wire carries no arbitrary callback URL.

A Codex Job contains exactly four fields:

```json
{"job_id":"...","workspace":"...","sender":"...","instruction_base64":"..."}
```

Upload remains a separate JSON operation issued after implementation or review. Dispatch is determined from the parsed JSON object: if it contains `operation`, route to the upload parser; otherwise route to the Codex Job parser. The upload object contains exactly five fields:

```json
{
  "operation": "upload",
  "job_id": "...",
  "workspace": "...",
  "sender": "...",
  "paths": ["..."]
}
```

`sender` is mandatory, a non-empty string, and must match a configured `senders` key for both operations. Legacy objects without `sender` are rejected; there is no backward compatibility or implicit callback selection. Existing strict field validation remains: extra or missing fields are rejected, `operation` must equal `upload`, and `paths` must be a non-empty array of non-empty strings with no duplicates. Path strings use `/` separators only; any path containing a backslash is rejected.

`operation` is not added to Jobs as an optional or ignored field. Existing Job ID, workspace, instruction UTF-8/Base64, and upload path validation rules remain in force.

For both wires, the sending tool mechanically performs UTF-8/Base64 encoding where applicable, JSON serialization, and Slack send in one tool execution. LLM-generated or manually composed Base64, copied Base64 between steps, and manually composed JSON escaping remain prohibited.

## 5. Path handling

Every selected path is relative to the configured workspace root and uses `/` separators. Before creating the Drive Job folder or uploading any file, `conduit` validates every requested path and rejects:

- paths containing a backslash;
- absolute paths;
- parent traversal;
- paths that resolve outside the workspace, including through a symlink escape;
- missing files; and
- directories.

One invalid path rejects the entire request before any Drive side effect. A minimal implementation may resolve the workspace root and each path, require the resolved path to remain under the root, and require it to be a regular file. Recursive directory upload is out of scope. These are narrow input checks, not a new filesystem-security framework.

## 6. Minimal Google Drive design

Only the small, proven implementation techniques from the old `chatgpt-agent` `drive_store.py` are candidates for reuse or reference:

- OAuth credentials and token refresh;
- Google Drive v3 service creation;
- a direct child Job-folder existence check and create under a configured parent folder ID;
- `MediaFileUpload`; and
- sequential multi-file upload.

The old artifact lifecycle, manifest, validator, hashes, provenance, trust model, context harness, and protocol architecture must not be imported.

Candidate authentication flow:

```text
credentials.json -> OAuth -> token.json -> refresh
```

`credentials.json` and `token.json` are local secrets/state and must be outside every configured workspace, because `conduit` itself is a registered workspace and these files must never become upload candidates. Prefer a small external local state/config location such as `%APPDATA%/conduit/`; their exact paths may be configuration values. They remain untracked by Git.

Candidate dependencies are:

```text
google-api-python-client
google-auth
google-auth-oauthlib
```

They are design candidates only. v0.3 design review does not add dependencies or credentials.

Human setup creates or selects `My Drive/chatgpt/jobs` once and stores its Google Drive folder ID in `conduit` configuration. `conduit` does not discover `chatgpt` or `jobs` by walking or searching folder names. For an upload, it checks for a child folder named exactly `job_id` directly under the configured `jobs_folder_id`. If one exists, it rejects the entire operation before uploading any file. Otherwise it creates exactly that one child folder; there is no `artifacts` subfolder.

One `job_id` permits one upload operation. A re-upload requires a new ID, such as a suffixed Job ID. v0.3 has no retry, version, update, or overwrite semantics.

Each selected file is uploaded sequentially with its workspace-relative path string as the Drive file name—for example, `tests/test_llm.py`, not `test_llm.py`. The Job folder remains flat while preserving source location and avoiding basename collisions. MIME type guessing is not required; `MediaFileUpload` may use its default behavior.

On success, the result is minimal: `job_id`, `uploaded n/m`, and the Job-folder URL if available from the Drive response or API. On failure, it includes the failed path and a one-line error when applicable. `conduit` does not automatically retry, enqueue, persist, reconcile, roll back, create a manifest, or record the operation in a result database.

## 7. State and ownership

`conduit` remains stateless. It may hold only the short-lived in-process state required to validate and perform the current operation.

Git remains the source and development baseline. Drive is external Job artifact storage for explicitly selected outputs; it is not a Git replacement, development baseline, source-of-truth system, or artifact lifecycle manager.

ChatGPT or a human decides which files to upload and when. `conduit` resolves the workspace, validates the supplied paths, performs the upload, and reports the result. It does not judge artifact quality, completeness, provenance, or promotion status.

## 8. v0.3 non-goals

The following are explicitly outside v0.3:

- artifact discovery, lifecycle, versioning, or a manifest framework;
- Drive sync, download, restore, cleanup, general folder-name search, cache, or database;
- recursive directory upload;
- background or parallel upload;
- automatic retry or retry queue;
- persistence, reconciliation, or rollback;
- Notion integration;
- Claude Code execution; and
- multi-agent execution or orchestration.

The broader standing exclusions also remain: no autonomous planning, workflow engine, trust system, context harness, artifact-management system, general plugin architecture, dashboard, or distributed execution.

## 9. End-to-end success criterion

v0.3 succeeds when an explicit upload request for the listed KAIROS files:

1. resolves the configured KAIROS workspace;
2. validates all workspace-relative file paths before any Drive side effect;
3. confirms no child named `job_id` exists under the configured `jobs_folder_id`, then creates that one child folder;
4. uploads all eight listed files there sequentially, using each workspace-relative path as its Drive file name; and
5. returns the minimal result to ChatGPT.

Before that real KAIROS upload, the single-file E2E must verify that the Drive API accepts `/` in a file name and returns or displays that name as expected. If the real API disproves this assumption, fix only that observed issue before the multi-file E2E. The multi-file E2E then verifies the complete sequential behavior and all-or-nothing prevalidation.

## 10. Development and review order

Work proceeds in this order:

```text
design update
-> minimal implementation
-> single-file E2E, including "/" in the Drive file name
-> multi-file E2E
-> KAIROS real upload of the listed eight files
-> only observed fixes
-> v0.3 complete
```

No Drive implementation or dependency addition occurs during the design-update step.

For the proposed v0.3.x revision, review this design in ChatGPT first. Migration then updates `config.toml`, both parsers and dispatch, and callback selection for Codex and Upload; updates tests and README; and runs end-to-end checks for both paths, including a cross-workspace callback and rejection of legacy wires without `sender`. After implementation and validation, update the Notion page `chatgpt development rules` separately with a concise dated change-history section. This design Job does not modify Notion.

## 11. Anti-bloat rules

Before adding any mechanism, ask:

> Is it required for the proven v0.2 path or the explicit v0.3 upload E2E?

If not, do not add it. Prefer existing platform behavior from ChatGPT, Codex, Git, Slack, the OS, and Google Drive over duplicating it inside `conduit`.

Design and implementation changes must address actual observed problems only. Do not add speculative abstraction, recovery machinery, protocol flexibility, security frameworks, or lifecycle concepts because they might become useful later. Keep the operation synchronous, sequential, explicit, and small.

The sender revision adds no sender manager, routing framework, extra abstraction, or fallback behavior.

## 12. v0.3 definition

`conduit` v0.3 is the proven v0.2 ChatGPT-to-Codex conduit plus one reviewed, explicit operation that uploads selected workspace-relative files to `My Drive/chatgpt/jobs/<job_id>/` and reports the outcome to ChatGPT.

Nothing in v0.3 changes `conduit` into an agent or an artifact-management system.

## 13. Proposed next-version extension: ChatGPT <-> dot messages

**Design proposal for ChatGPT review before implementation.** This extension adds one independent `message` operation on `#dot-jobs` (`C0C8ABT93J7`) in the ChatGPT Agent Slack workspace. Existing `#codex-jobs` (`C0C4J6WMLJH`) remains the Codex Job and Drive Upload channel, with its strict four-field Job and five-field Upload contracts unchanged. Channel selection isolates the new parser; it does not create a generic dispatcher or agent router.

**Wire update after E2E review:** Slack URL autolinking was observed to corrupt raw JSON content. The current inbound dot wire therefore carries UTF-8 Base64 in `content_base64`. Historical observations and the original v0.3 proposal below remain recorded as they occurred.

The dot-to-ChatGPT wire is a standalone JSON object with exactly five fields, in this form:

```json
{"operation":"message","message_id":"...","sender":"dot","receiver":"conduit","content_base64":"<UTF-8 Base64>"}
```

The five fields are `operation`, `message_id`, `sender`, `receiver`, and `content_base64`; `operation` is `message` and `sender` is `dot`. Dot must use a tool or programmatic conversion to Base64-encode its UTF-8 text and verify the result by reverse decoding; it must never guess Base64 manually. Dot's reply has no Markdown fence, prefix, or explanatory text. Slack channel and thread identity are Slack metadata, not JSON wire fields. ChatGPT-to-dot Slack text starts with a real `<@U0C6B7D0M51>` mention followed by an instruction and optionally a JSON envelope with `sender` and `receiver` reversed. Dot replies with standalone JSON in that same Slack thread. Conduit does not need to parse outgoing ChatGPT-to-dot text. Inspect actual inbound Slack event formatting before choosing normalization; do not silently add `html.unescape`.

Proposed `config.toml` addition for the next version (not a change to the current file):

```toml
[dot]
channel_id = "C0C8ABT93J7"
user_id = "U0C6B7D0M51"
```

The existing `#codex-jobs` channel remains in `SLACK_CHANNEL_ID` in `.env` and is not migrated by this proposal. Existing `[senders]` callback URLs remain unchanged.

For inbound dot-to-ChatGPT delivery, `conduit` subscribes to `#dot-jobs` and processes only a validated `message` object from configured Slack user `U0C6B7D0M51` in configured channel `C0C8ABT93J7`. The `sender` field must equal `dot`; the JSON string alone is not authentication. Require a non-empty `message_id`, a non-empty `content_base64` string that strictly decodes as Base64 and UTF-8 to non-empty text, and a `receiver` matching a registered ChatGPT sender such as `conduit`. Reject the old `content` wire, extra fields, malformed or unaddressed events without callback. Resolve the destination through the existing `[senders.<name>].callback_url` registration (the `conduit` chat is https://chatgpt.com/c/6ac26caf-b63c-83ec-83d0-9f8d926c3df7), never through a URL supplied in the message. Forward the decoded content with attribution identifying dot and its Slack thread, using the existing ChatGPT callback and logging conventions. No Codex execution or Drive upload occurs on this path.

Ignore irrelevant events, echoes, and messages from other Slack senders. Process only dot-authored, receiver-targeted, validated messages. Do not add an event-ID cache or other speculative deduplication state. If actual Slack redelivery causes a duplicate callback, investigate the observed behavior and add the smallest fix. The remaining delivery blocker is Slack app membership in `#dot-jobs`, appropriate event subscription, and actual Socket Mode delivery to conduit; none of these is proven by dot's reply.

### Review checklist and minimal E2E

- [x] In `#dot-jobs`, parent message `1791787454.634039` mentioned dot and instructed a JSON reply. Dot user `U0C6B7D0M51` replied at `1791787473.338719` in the same thread with exactly `{"operation":"message","message_id":"dot-test-001","sender":"dot","receiver":"conduit","content":"DOT_JSON_OK"}` and no fence or explanatory text. This proves dot can emit the required JSON; it does not prove conduit receives the channel.
- [ ] Confirm Slack app membership, event subscription, Socket Mode receipt, and actual Slack user/channel/thread fields at conduit.
- [ ] Verify conduit accepts a dot-authored valid reply, logs it, and delivers its content to the registered `conduit` ChatGPT callback end to end.
- [ ] Verify echoes and irrelevant events are ignored; reject malformed or unaddressed content and a forged `sender=dot` from another Slack user. Check for actual redelivery before designing deduplication.

Keep implementation changes minimal: one channel-specific message path using existing callback and logs. Add no polling service, orchestration, generalized routing, persistent message database, retries, or arbitrary callback URL. The next review gate is actual delivery to conduit through Socket Mode, followed by an end-to-end callback to conduit ChatGPT.
