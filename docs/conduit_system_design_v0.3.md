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

The v0.2 execution contract remains unchanged by this design. In particular, Drive upload is not inferred from a normal Job and is not added to the existing three-field Job JSON.

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

## 4. Upload operation and wire contract

Upload is a separate JSON operation issued after implementation or review. Dispatch is determined from the parsed JSON object: if it contains the key `operation`, route it to the upload parser; otherwise route it to the existing Codex Job parser.

The upload object contains exactly:

```json
{
  "operation": "upload",
  "job_id": "...",
  "workspace": "...",
  "paths": ["..."]
}
```

`operation` must equal `upload`. `paths` must be a non-empty array of non-empty strings with no duplicates. Path strings use `/` separators only; any path containing a backslash is rejected.

The existing strict Codex Job parser is unchanged: a Job remains JSON containing exactly `job_id`, `workspace`, and `instruction_base64`. `operation` is not added to Jobs as an optional or ignored field.

As with an existing Job, the sender mechanically JSON-serializes and Slack-sends the upload object in one tool execution. Manually composed JSON escaping is prohibited.

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

## 11. Anti-bloat rules

Before adding any mechanism, ask:

> Is it required for the proven v0.2 path or the explicit v0.3 upload E2E?

If not, do not add it. Prefer existing platform behavior from ChatGPT, Codex, Git, Slack, the OS, and Google Drive over duplicating it inside `conduit`.

Design and implementation changes must address actual observed problems only. Do not add speculative abstraction, recovery machinery, protocol flexibility, security frameworks, or lifecycle concepts because they might become useful later. Keep the operation synchronous, sequential, explicit, and small.

## 12. v0.3 definition

`conduit` v0.3 is the proven v0.2 ChatGPT-to-Codex conduit plus one reviewed, explicit operation that uploads selected workspace-relative files to `My Drive/chatgpt/jobs/<job_id>/` and reports the outcome to ChatGPT.

Nothing in v0.3 changes `conduit` into an agent or an artifact-management system.
