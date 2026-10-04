import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import conduit


class ConduitTests(unittest.TestCase):
    def setUp(self):
        notify_patcher = patch("conduit.notify_chatgpt")
        self.notify = notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

    @staticmethod
    def workspace_config(path, callback_url="https://chatgpt.com/c/test"):
        return {"path": path, "callback_url": callback_url}

    def test_workspace_and_callback_resolution(self):
        workspaces = conduit.load_workspaces()
        self.assertEqual(workspaces["conduit"]["path"], r"C:\dev\conduit")
        self.assertEqual(workspaces["kairos"]["path"], r"C:\dev\kairos")
        self.assertEqual(
            workspaces["conduit"]["callback_url"],
            "https://chatgpt.com/c/6ac26caf-b63c-83ec-83d0-9f8d926c3df7",
        )
        self.assertEqual(
            workspaces["kairos"]["callback_url"],
            "https://chatgpt.com/c/6ac26c6e-9710-83ee-b641-9f17d64cd7a9",
        )

    def test_invalid_config_errors_are_concise(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            directory = Path(directory)
            with self.assertRaisesRegex(ValueError, "config.toml not found"):
                conduit.load_workspaces(directory / "missing.toml")
            config_file = directory / "config.toml"
            config_file.write_text("[workspaces.test]\ncallback_url = 'url'\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "has no path"):
                conduit.load_workspaces(config_file)
            config_file.write_text("[workspaces.test]\npath = 'path'\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "has no callback_url"):
                conduit.load_workspaces(config_file)

    def test_load_dotenv(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "SLACK_BOT_TOKEN=from-file\nSLACK_APP_TOKEN=app-file\n"
                "SLACK_CHANNEL_ID=channel-file\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                conduit.load_dotenv(env_file)
                self.assertEqual(os.environ["SLACK_BOT_TOKEN"], "from-file")
                self.assertEqual(os.environ["SLACK_APP_TOKEN"], "app-file")
                self.assertEqual(os.environ["SLACK_CHANNEL_ID"], "channel-file")

    def test_load_dotenv_does_not_override_environment(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("SLACK_BOT_TOKEN=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "from-os"}, clear=True):
                conduit.load_dotenv(env_file)
                self.assertEqual(os.environ["SLACK_BOT_TOKEN"], "from-os")

    def test_ping(self):
        with self.assertLogs(conduit.logger, level="INFO") as logs:
            self.assertEqual(conduit.handle_text(conduit.PING), conduit.PONG)
        self.assertIn("PING PONG", logs.output[0])

    def test_logging_rotation_settings(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            try:
                conduit.setup_logging(Path(directory) / "conduit.log")
                handler = next(
                    item for item in conduit.logger.handlers
                    if isinstance(item, conduit.RotatingFileHandler)
                )
                self.assertEqual(handler.maxBytes, 10 * 1024 * 1024)
                self.assertEqual(handler.backupCount, 10)
                self.assertTrue(any(
                    type(item) is conduit.logging.StreamHandler
                    for item in conduit.logger.handlers
                ))
            finally:
                for handler in conduit.logger.handlers[:]:
                    handler.close()
                    conduit.logger.removeHandler(handler)
                conduit.logger.addHandler(conduit.logging.NullHandler())

    def test_slack_attributed_ping(self):
        text = "LOCAL-AGENT PING *使用して送信されました* <@U0C4T02QR9A>"
        self.assertEqual(
            conduit.handle_text(conduit.remove_chatgpt_attribution(text)), conduit.PONG
        )

    def test_slack_attributed_job_only_removes_known_suffix(self):
        job = json.dumps({
            "job_id": "conduit-e2e-001", "workspace": "test", "instruction": "test"
        })
        attribution = "\n*使用して送信されました* <@U0C4T02QR9A>"
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(0, "done", "")
            ):
                attributed = conduit.remove_chatgpt_attribution(job + attribution)
                self.assertEqual(conduit.handle_text(attributed), "done")
                self.assertIn("exit_code: 2", conduit.handle_text(job + " SOMETHING"))

    def test_unknown_workspace_is_rejected(self):
        with self.assertLogs(conduit.logger, level="ERROR") as logs:
            response = conduit.handle_text(json.dumps({
                "job_id": "bad-1", "workspace": "unknown", "instruction": "test"
            }))
        self.assertIn("job_id: bad-1", response)
        self.assertIn("exit_code: 2", response)
        self.assertIn("unknown workspace", response)
        self.assertIn("Job parse/validation error", logs.output[0])

    def test_extra_field_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}):
                response = conduit.handle_text(json.dumps({
                    "job_id": "bad-2", "workspace": "test",
                    "instruction": "test", "extra": True,
                }))
        self.assertIn("exit_code: 2", response)

    def test_success_returns_only_final_message(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(0, "done", "diagnostic")
            ):
                with self.assertLogs(conduit.logger, level="INFO") as logs:
                    response = conduit.handle_text(json.dumps({
                        "job_id": "ok-1", "workspace": "test", "instruction": "test"
                    }))
        self.assertEqual(response, "done")
        self.assertTrue(any("JOB START job_id=ok-1 workspace=test" in line for line in logs.output))
        self.assertTrue(any("JOB END job_id=ok-1 exit_code=0" in line for line in logs.output))
        self.notify.assert_called_once_with("https://chatgpt.com/c/test", "done")

    def test_kairos_job_uses_kairos_callback_url(self):
        kairos_url = conduit.WORKSPACES["kairos"]["callback_url"]
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            kairos = self.workspace_config(workspace, kairos_url)
            with patch.dict(conduit.WORKSPACES, {"kairos": kairos}, clear=True), patch.object(
                conduit, "run_job", return_value=(0, "kairos result", "")
            ):
                conduit.handle_text(json.dumps({
                    "job_id": "kairos-1",
                    "workspace": "kairos",
                    "instruction": "test",
                }))
        self.notify.assert_called_once_with(kairos_url, "kairos result")

    def test_failure_limits_stderr_to_twenty_lines(self):
        stderr = "\n".join(f"line {number}" for number in range(25))
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(7, "", stderr)
            ):
                response = conduit.handle_text(json.dumps({
                    "job_id": "fail-1", "workspace": "test", "instruction": "test"
                }))
        self.assertNotIn("line 4\n", response)
        self.assertIn("line 5\n", response)
        self.assertEqual(len(response.split("stderr:\n", 1)[1].splitlines()), 20)
        self.notify.assert_called_once_with("https://chatgpt.com/c/test", response)

    def test_callback_failure_does_not_repeat_or_escape(self):
        self.notify.side_effect = RuntimeError("browser unavailable")
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(0, "done", "")
            ) as run_job, self.assertLogs(conduit.logger, level="ERROR") as logs:
                response = conduit.handle_text(json.dumps({
                    "job_id": "ok-3", "workspace": "test", "instruction": "test"
                }))
        self.assertEqual(response, "done")
        run_job.assert_called_once()
        self.notify.assert_called_once_with("https://chatgpt.com/c/test", "done")
        self.assertTrue(any("ChatGPT callback failed" in line for line in logs.output))

    def test_run_job_passes_instruction_on_stdin(self):
        def fake_run(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_text("final", encoding="utf-8")
            self.assertEqual(command[command.index("-s") + 1], "workspace-write")
            self.assertEqual(command[-1], "-")
            self.assertEqual(kwargs["input"], "日本語 instruction")
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")
            return type(
                "Result", (), {"returncode": 0, "stdout": "codex details", "stderr": ""}
            )()

        with tempfile.TemporaryDirectory(dir=".") as workspace:
            job = {"job_id": "ok-2", "workspace": "test", "instruction": "日本語 instruction"}
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch(
                "conduit.shutil.which", return_value=r"C:\bin\codex.cmd"
            ), patch("conduit.subprocess.run", side_effect=fake_run):
                with self.assertLogs(conduit.logger, level="INFO") as logs:
                    result = conduit.run_job(job)
        self.assertEqual(result, (0, "final", ""))
        self.assertTrue(any("Codex stdout:\ncodex details" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
