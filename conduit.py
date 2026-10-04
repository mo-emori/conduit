"""Minimal Slack-to-Codex worker for conduit v0.1."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from callback import notify_chatgpt


WORKSPACES = {
    "kairos": r"C:\dev\kairos",
    "conduit": r"C:\dev\conduit",
}

PING = "LOCAL-AGENT PING"
PONG = "LOCAL-AGENT PONG — Worker ready"
JOB_FIELDS = {"job_id", "workspace", "instruction"}
CHATGPT_ATTRIBUTION = re.compile(
    r"\s+\*使用して送信されました\*\s+<@U[A-Z0-9]+>\s*\Z"
)
_job_lock = threading.Lock()


def error_message(job_id: object, exit_code: int, stderr: str) -> str:
    tail = "\n".join(stderr.splitlines()[-20:]) or "(no stderr)"
    return f"job_id: {job_id}\nexit_code: {exit_code}\nstderr:\n{tail}"


def remove_chatgpt_attribution(text: str) -> str:
    return CHATGPT_ATTRIBUTION.sub("", text)


def callback_result(message: str) -> None:
    try:
        notify_chatgpt(message)
    except Exception as exc:
        print(f"ChatGPT callback failed: {exc}")


def parse_job(text: str) -> dict[str, str]:
    try:
        job = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Job JSON: {exc.msg}") from exc

    if not isinstance(job, dict) or set(job) != JOB_FIELDS:
        raise ValueError("Job must contain exactly: job_id, workspace, instruction")
    if not all(isinstance(job[field], str) and job[field] for field in JOB_FIELDS):
        raise ValueError("all Job fields must be non-empty strings")
    if job["workspace"] not in WORKSPACES:
        raise ValueError(f"unknown workspace: {job['workspace']}")
    if not Path(WORKSPACES[job["workspace"]]).is_dir():
        raise ValueError(f"workspace does not exist: {WORKSPACES[job['workspace']]}")
    return job


def run_job(job: dict[str, str]) -> tuple[int, str, str]:
    codex = shutil.which("codex")
    if not codex:
        return 127, "", "codex executable not found"

    output_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as output:
            output_path = output.name
        command = [
            codex,
            "exec",
            "-C",
            WORKSPACES[job["workspace"]],
            "-s",
            "workspace-write",
            "-o",
            output_path,
            "-",
        ]
        completed = subprocess.run(
            command,
            input=job["instruction"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        final_message = Path(output_path).read_text(encoding="utf-8", errors="replace")
        return completed.returncode, final_message, completed.stderr
    except OSError as exc:
        return 126, "", str(exc)
    finally:
        if output_path:
            Path(output_path).unlink(missing_ok=True)


def handle_text(text: str) -> str:
    stripped = text.strip()
    if stripped == PING or stripped.startswith(f"{PING} *"):
        return PONG

    job_id: object = "(unknown)"
    try:
        decoded = json.loads(text)
        if isinstance(decoded, dict):
            job_id = decoded.get("job_id", job_id)
        job = parse_job(text)
        job_id = job["job_id"]
    except (json.JSONDecodeError, ValueError) as exc:
        return error_message(job_id, 2, str(exc))

    with _job_lock:
        exit_code, final_message, stderr = run_job(job)
        if exit_code == 0 and final_message:
            result = final_message
        else:
            if exit_code == 0:
                exit_code, stderr = 1, stderr or "Codex produced no final message"
            result = error_message(job_id, exit_code, stderr)
        callback_result(result)
    return result


def main() -> None:
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    channel_id = os.environ["SLACK_CHANNEL_ID"]

    @app.message(re.compile(r"[\s\S]*"))
    def receive(message, say):
        if message.get("channel") != channel_id:
            return
        text = message.get("text")
        if isinstance(text, str):
            text = remove_chatgpt_attribution(text)
            say(text=handle_text(text), thread_ts=message.get("thread_ts") or message.get("ts"))

    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
