"""Minimal Slack-to-Codex worker for conduit v0.1."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from logging.handlers import RotatingFileHandler
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
ENV_KEYS = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID")
CHATGPT_ATTRIBUTION = re.compile(
    r"\s+\*使用して送信されました\*\s+<@U[A-Z0-9]+>\s*\Z"
)
_job_lock = threading.Lock()
logger = logging.getLogger("conduit")
logger.addHandler(logging.NullHandler())


def setup_logging(log_path: Path | None = None) -> None:
    path = log_path or Path(__file__).with_name("logs") / "conduit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    file = RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    stream.setFormatter(formatter)
    file.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(stream)
    logger.addHandler(file)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(__file__).with_name(".env")
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        if separator and key in ENV_KEYS and key not in os.environ:
            os.environ[key] = value.strip()


def error_message(job_id: object, exit_code: int, stderr: str) -> str:
    tail = "\n".join(stderr.splitlines()[-20:]) or "(no stderr)"
    return f"job_id: {job_id}\nexit_code: {exit_code}\nstderr:\n{tail}"


def remove_chatgpt_attribution(text: str) -> str:
    return CHATGPT_ATTRIBUTION.sub("", text)


def callback_result(message: str) -> None:
    try:
        notify_chatgpt(message)
    except Exception as exc:
        logger.error("ChatGPT callback failed: %s", exc)


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
        logger.info("Codex stdout:\n%s", completed.stdout)
        final_message = Path(output_path).read_text(encoding="utf-8", errors="replace")
        return completed.returncode, final_message, completed.stderr
    except OSError as exc:
        logger.error("Codex execution error job_id=%s error=%s", job["job_id"], exc)
        return 126, "", str(exc)
    finally:
        if output_path:
            Path(output_path).unlink(missing_ok=True)


def handle_text(text: str) -> str:
    stripped = text.strip()
    if stripped == PING or stripped.startswith(f"{PING} *"):
        logger.info("PING PONG")
        return PONG

    job_id: object = "(unknown)"
    try:
        decoded = json.loads(text)
        if isinstance(decoded, dict):
            job_id = decoded.get("job_id", job_id)
        job = parse_job(text)
        job_id = job["job_id"]
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Job parse/validation error job_id=%s error=%s", job_id, exc)
        return error_message(job_id, 2, str(exc))

    with _job_lock:
        logger.info("JOB START job_id=%s workspace=%s", job_id, job["workspace"])
        exit_code, final_message, stderr = run_job(job)
        logger.info("JOB END job_id=%s exit_code=%s", job_id, exit_code)
        if exit_code != 0:
            stderr_tail = "\n".join(stderr.splitlines()[-20:]) or "(no stderr)"
            logger.error(
                "Codex execution error job_id=%s exit_code=%s stderr:\n%s",
                job_id, exit_code, stderr_tail,
            )
        if exit_code == 0 and final_message:
            result = final_message
        else:
            if exit_code == 0:
                exit_code, stderr = 1, stderr or "Codex produced no final message"
            result = error_message(job_id, exit_code, stderr)
        callback_result(result)
    return result


def main() -> None:
    setup_logging()
    load_dotenv()
    missing = [key for key in ENV_KEYS if not os.environ.get(key)]
    if missing:
        logger.error("Missing required settings: %s", ", ".join(missing))
        raise SystemExit(f"Missing required settings: {', '.join(missing)}")

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
