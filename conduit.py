"""Minimal Slack-to-Codex worker for conduit v0.3."""

import base64
import binascii
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from callback import notify_chatgpt
from drive_store import upload_files


CONFIG_PATH = Path(__file__).with_name("config.toml")


def load_workspaces(path: Path = CONFIG_PATH) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"config.toml not found: {path}")
    with path.open("rb") as config_file:
        config = tomllib.load(config_file)
    workspaces = config.get("workspaces", {})
    if not isinstance(workspaces, dict):
        raise ValueError("config.toml: workspaces must be a table")
    for name, workspace in workspaces.items():
        if not isinstance(workspace, dict) or not workspace.get("path"):
            raise ValueError(f"config.toml: workspace '{name}' has no path")
        if not workspace.get("callback_url"):
            raise ValueError(f"config.toml: workspace '{name}' has no callback_url")
    return workspaces


def load_job_path_prepend(path: Path = CONFIG_PATH) -> list[str]:
    with path.open("rb") as config_file:
        entries = tomllib.load(config_file).get("job_path_prepend", [])
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        raise ValueError("config.toml: job_path_prepend must be a list of strings")
    return entries


WORKSPACES = load_workspaces()
JOB_PATH_PREPEND = load_job_path_prepend()

PING = "LOCAL-AGENT PING"
PONG = "LOCAL-AGENT PONG — Worker ready"
JOB_FIELDS = {"job_id", "workspace", "instruction_base64"}
UPLOAD_FIELDS = {"operation", "job_id", "workspace", "paths"}
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


def build_job_env(job_tmp: Path) -> dict[str, str]:
    env = os.environ.copy()
    conduit_scripts = os.path.normcase(
        os.path.normpath(str(Path(sys.prefix) / "Scripts"))
    )
    path_entries = []
    prepended = set()
    for entry in JOB_PATH_PREPEND:
        normalized = os.path.normcase(os.path.normpath(entry))
        if normalized not in prepended:
            path_entries.append(entry)
            prepended.add(normalized)
    path_entries.extend(
        entry for entry in env.get("PATH", "").split(os.pathsep)
        if os.path.normcase(os.path.normpath(entry)) not in prepended
        and os.path.normcase(os.path.normpath(entry)) != conduit_scripts
    )
    env["PATH"] = os.pathsep.join(path_entries)
    for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env["TMPDIR"] = str(job_tmp)
    return env


def error_message(job_id: object, exit_code: int, stderr: str) -> str:
    tail = "\n".join(stderr.splitlines()[-20:]) or "(no stderr)"
    return f"job_id: {job_id}\nexit_code: {exit_code}\nstderr:\n{tail}"


def remove_chatgpt_attribution(text: str) -> str:
    return CHATGPT_ATTRIBUTION.sub("", text)


def callback_result(
    target_url: str, message: str, job_id: str, workspace: str
) -> None:
    logger.info(
        "CALLBACK START job_id=%s workspace=%s", job_id, workspace
    )
    try:
        notify_chatgpt(target_url, message)
    except Exception as exc:
        concise_error = str(exc).replace("\r", " ").replace("\n", " ")
        logger.error(
            "CALLBACK ERROR job_id=%s error=%s", job_id, concise_error
        )
    else:
        logger.info("CALLBACK END job_id=%s", job_id)


def parse_json_object(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid fields")
    return value


def parse_job_object(job: dict) -> dict[str, str]:
    job = job.copy()
    if set(job) != JOB_FIELDS:
        raise ValueError("invalid fields")
    if not all(isinstance(job[field], str) for field in JOB_FIELDS):
        raise ValueError("invalid fields")
    if not job["job_id"] or not job["workspace"]:
        raise ValueError("invalid fields")
    try:
        instruction_bytes = base64.b64decode(
            job["instruction_base64"], validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid instruction Base64") from exc
    try:
        instruction = instruction_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid instruction UTF-8") from exc
    if not instruction.strip():
        raise ValueError("empty instruction")
    if job["workspace"] not in WORKSPACES:
        raise ValueError("unknown workspace")
    workspace_path = WORKSPACES[job["workspace"]]["path"]
    if not Path(workspace_path).is_dir():
        raise ValueError(f"workspace does not exist: {workspace_path}")
    del job["instruction_base64"]
    job["instruction"] = instruction
    return job


def parse_job(text: str) -> dict[str, str]:
    return parse_job_object(parse_json_object(text))


def parse_upload(value: dict) -> dict:
    if set(value) != UPLOAD_FIELDS or value.get("operation") != "upload":
        raise ValueError("invalid fields")
    if not isinstance(value.get("job_id"), str) or not value["job_id"]:
        raise ValueError("invalid fields")
    if not isinstance(value.get("workspace"), str) or not value["workspace"]:
        raise ValueError("invalid fields")
    if value["workspace"] not in WORKSPACES:
        raise ValueError("unknown workspace")
    paths = value.get("paths")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(item, str) and item for item in paths
    ):
        raise ValueError("invalid paths")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate paths")
    if any("\\" in item for item in paths):
        raise ValueError("backslash path")
    return value.copy()


def validate_upload_paths(workspace_path: str, paths: list[str]) -> list[tuple[Path, str]]:
    root = Path(workspace_path).resolve()
    if not root.is_dir():
        raise ValueError(f"workspace does not exist: {workspace_path}")
    validated = []
    for relative in paths:
        posix_path = PurePosixPath(relative)
        if (posix_path.is_absolute() or PureWindowsPath(relative).is_absolute()
                or PureWindowsPath(relative).drive or ".." in posix_path.parts):
            raise ValueError(f"invalid path: {relative}")
        local_path = (root / Path(*posix_path.parts)).resolve()
        try:
            local_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path outside workspace: {relative}") from exc
        if not local_path.exists():
            raise ValueError(f"missing path: {relative}")
        if not local_path.is_file():
            raise ValueError(f"not a file: {relative}")
        validated.append((local_path, relative))
    return validated


def load_drive_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    with path.open("rb") as config_file:
        drive = tomllib.load(config_file).get("drive")
    required = ("jobs_folder_id", "credentials_file", "token_file")
    if not isinstance(drive, dict) or not all(
        isinstance(drive.get(key), str) and drive[key] for key in required
    ):
        raise ValueError("invalid Drive config")
    for key in ("credentials_file", "token_file"):
        secret_path = Path(drive[key]).resolve()
        for workspace in WORKSPACES.values():
            try:
                secret_path.relative_to(Path(workspace["path"]).resolve())
            except ValueError:
                continue
            raise ValueError(f"Drive {key} must be outside workspaces")
    return {key: drive[key] for key in required}


def run_job(job: dict[str, str]) -> tuple[int, str, str]:
    codex = shutil.which("codex")
    if not codex:
        return 127, "", "codex executable not found"

    output_path = ""
    job_tmp = ""
    try:
        workspace_path = Path(WORKSPACES[job["workspace"]]["path"]).resolve()
        temp_root = workspace_path / ".conduit-tmp"
        temp_root.mkdir(exist_ok=True)
        job_tmp = tempfile.mkdtemp(prefix="job-", dir=temp_root)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as output:
            output_path = output.name
        command = [
            codex,
            "exec",
            "-C",
            str(workspace_path),
            "-s",
            "workspace-write",
            "-o",
            output_path,
            "-",
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=build_job_env(Path(job_tmp)),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise OSError("failed to open Codex process pipes")

        stderr_lines = []

        def read_stderr() -> None:
            try:
                for line in iter(process.stderr.readline, ""):
                    stderr_lines.append(line)
                    logged_line = line.rstrip("\r\n")
                    if logged_line:
                        logger.info("Codex stderr: %s", logged_line)
            finally:
                process.stderr.close()

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()
        process.stdin.write(job["instruction"])
        process.stdin.close()
        for line in process.stdout:
            line = line.rstrip("\r\n")
            if line:
                logger.info("Codex stdout: %s", line)
        exit_code = process.wait()
        stderr_thread.join()
        stderr = "".join(stderr_lines)
        final_message = Path(output_path).read_text(encoding="utf-8", errors="replace")
        return exit_code, final_message, stderr
    except OSError as exc:
        logger.error("Codex execution error job_id=%s error=%s", job["job_id"], exc)
        return 126, "", str(exc)
    finally:
        if output_path:
            Path(output_path).unlink(missing_ok=True)
        if job_tmp:
            shutil.rmtree(job_tmp, ignore_errors=True)


def handle_text(text: str) -> str:
    stripped = text.strip()
    if stripped == PING or stripped.startswith(f"{PING} *"):
        logger.info("PING PONG")
        return PONG

    try:
        value = parse_json_object(text)
    except ValueError as exc:
        logger.error("Job parse/validation error: %s", exc)
        return f"INVALID_JOB: {exc}"

    is_upload = "operation" in value
    try:
        request = parse_upload(value) if is_upload else parse_job_object(value)
        job_id = request["job_id"]
    except ValueError as exc:
        kind = "Upload" if is_upload else "Job"
        logger.error("%s parse/validation error: %s", kind, exc)
        return f"{'UPLOAD_ERROR' if is_upload else 'INVALID_JOB'}: {exc}"

    with _job_lock:
        if is_upload:
            current_upload_path = None

            def log_upload_file(relative_path: str) -> None:
                nonlocal current_upload_path
                current_upload_path = relative_path
                logger.info("UPLOAD FILE job_id=%s path=%s", job_id, relative_path)

            try:
                validated = validate_upload_paths(
                    WORKSPACES[request["workspace"]]["path"], request["paths"]
                )
                logger.info(
                    "UPLOAD START job_id=%s workspace=%s files=%s",
                    job_id, request["workspace"], len(validated),
                )
                drive_config = load_drive_config()
                folder_url = upload_files(
                    drive_config, job_id, validated, on_file=log_upload_file
                )
                result = f"job_id: {job_id}; uploaded {len(validated)}/{len(validated)}"
                if folder_url:
                    result += f"; folder: {folder_url}"
                logger.info(
                    "UPLOAD END job_id=%s uploaded=%s/%s",
                    job_id, len(validated), len(validated),
                )
            except Exception as exc:
                concise_error = str(exc).replace(chr(10), " ")
                result = f"UPLOAD_ERROR job_id={job_id}: {concise_error}"
                if current_upload_path is None:
                    logger.error(
                        "UPLOAD ERROR job_id=%s error=%s", job_id, concise_error
                    )
                else:
                    log_error = concise_error.removeprefix(
                        f"{current_upload_path}: "
                    )
                    logger.error(
                        "UPLOAD ERROR job_id=%s path=%s error=%s",
                        job_id, current_upload_path, log_error,
                    )
            callback_result(
                WORKSPACES[request["workspace"]]["callback_url"],
                result,
                job_id,
                request["workspace"],
            )
            return result

        job = request
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
        callback_result(
            WORKSPACES[job["workspace"]]["callback_url"],
            result,
            job_id,
            job["workspace"],
        )
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
