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
        self.assertEqual(conduit.handle_text(conduit.PING), conduit.PONG)

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
            with patch.dict(conduit.WORKSPACES, {"test": workspace}), patch.object(
                conduit, "run_job", return_value=(0, "done", "")
            ):
                attributed = conduit.remove_chatgpt_attribution(job + attribution)
                self.assertEqual(conduit.handle_text(attributed), "done")
                self.assertIn("exit_code: 2", conduit.handle_text(job + " SOMETHING"))

    def test_unknown_workspace_is_rejected(self):
        response = conduit.handle_text(json.dumps({
            "job_id": "bad-1", "workspace": "unknown", "instruction": "test"
        }))
        self.assertIn("job_id: bad-1", response)
        self.assertIn("exit_code: 2", response)
        self.assertIn("unknown workspace", response)

    def test_extra_field_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": workspace}):
                response = conduit.handle_text(json.dumps({
                    "job_id": "bad-2", "workspace": "test",
                    "instruction": "test", "extra": True,
                }))
        self.assertIn("exit_code: 2", response)

    def test_success_returns_only_final_message(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": workspace}), patch.object(
                conduit, "run_job", return_value=(0, "done", "diagnostic")
            ):
                response = conduit.handle_text(json.dumps({
                    "job_id": "ok-1", "workspace": "test", "instruction": "test"
                }))
        self.assertEqual(response, "done")
        self.notify.assert_called_once_with("done")

    def test_failure_limits_stderr_to_twenty_lines(self):
        stderr = "\n".join(f"line {number}" for number in range(25))
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": workspace}), patch.object(
                conduit, "run_job", return_value=(7, "", stderr)
            ):
                response = conduit.handle_text(json.dumps({
                    "job_id": "fail-1", "workspace": "test", "instruction": "test"
                }))
        self.assertNotIn("line 4\n", response)
        self.assertIn("line 5\n", response)
        self.assertEqual(len(response.split("stderr:\n", 1)[1].splitlines()), 20)
        self.notify.assert_called_once_with(response)

    def test_callback_failure_does_not_repeat_or_escape(self):
        self.notify.side_effect = RuntimeError("browser unavailable")
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": workspace}), patch.object(
                conduit, "run_job", return_value=(0, "done", "")
            ) as run_job, patch("builtins.print") as output:
                response = conduit.handle_text(json.dumps({
                    "job_id": "ok-3", "workspace": "test", "instruction": "test"
                }))
        self.assertEqual(response, "done")
        run_job.assert_called_once()
        self.notify.assert_called_once_with("done")
        output.assert_called_once()

    def test_run_job_passes_instruction_on_stdin(self):
        def fake_run(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_text("final", encoding="utf-8")
            self.assertEqual(command[command.index("-s") + 1], "workspace-write")
            self.assertEqual(command[-1], "-")
            self.assertEqual(kwargs["input"], "日本語 instruction")
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        with tempfile.TemporaryDirectory(dir=".") as workspace:
            job = {"job_id": "ok-2", "workspace": "test", "instruction": "日本語 instruction"}
            with patch.dict(conduit.WORKSPACES, {"test": workspace}), patch(
                "conduit.shutil.which", return_value=r"C:\bin\codex.cmd"
            ), patch("conduit.subprocess.run", side_effect=fake_run):
                result = conduit.run_job(job)
        self.assertEqual(result, (0, "final", ""))


if __name__ == "__main__":
    unittest.main()
