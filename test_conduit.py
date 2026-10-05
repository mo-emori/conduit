import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import conduit
import drive_store


class ConduitTests(unittest.TestCase):
    def setUp(self):
        notify_patcher = patch("conduit.notify_chatgpt")
        self.notify = notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

    @staticmethod
    def workspace_config(path, callback_url="https://chatgpt.com/c/test"):
        return {"path": path, "callback_url": callback_url}

    @staticmethod
    def make_job(instruction="test", job_id="test-job", workspace="test"):
        return json.dumps({
            "job_id": job_id,
            "workspace": workspace,
            "instruction_base64": base64.b64encode(
                instruction.encode("utf-8")
            ).decode("ascii"),
        })

    @staticmethod
    def make_upload(paths=None, job_id="upload-job", workspace="test"):
        return json.dumps({
            "operation": "upload",
            "job_id": job_id,
            "workspace": workspace,
            "paths": paths if paths is not None else ["one.txt"],
        })

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
        self.assertEqual(
            conduit.load_job_path_prepend(),
            ["C:/Users/mttge/AppData/Local/Python/bin"],
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

    def test_build_job_env_sanitizes_python_and_prepends_configured_path(self):
        parent_env = {
            "PATH": (
                r"c:/DEV/CONDUIT/.VENV/Scripts/"
                + os.pathsep + r"C:\Windows\System32"
                + os.pathsep + r"C:\Users\mttge\AppData\Local\Microsoft\WindowsApps"
                + os.pathsep + r"C:\Tools"
            ),
            "VIRTUAL_ENV": "C:\\DEV\\CONDUIT\\.venv\\",
            "PYTHONPATH": r"C:\dev\conduit",
            "PYTHONHOME": r"C:\Python",
            "KEEP_ME": "yes",
        }
        prepend = r"C:\Users\mttge\AppData\Local\Python\bin"
        with patch.dict(os.environ, parent_env, clear=True), patch.object(
            conduit.sys, "prefix", r"C:\dev\conduit\.venv"
        ), patch.object(conduit, "JOB_PATH_PREPEND", [prepend, prepend.lower()]):
            job_env = conduit.build_job_env(Path(r"C:\dev\test\.conduit-tmp\job-test"))

        self.assertEqual(
            job_env["PATH"],
            prepend + os.pathsep + r"C:\Windows\System32"
            + os.pathsep + r"C:\Users\mttge\AppData\Local\Microsoft\WindowsApps"
            + os.pathsep + r"C:\Tools",
        )
        for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(key, job_env)
        self.assertEqual(job_env["KEEP_ME"], "yes")
        self.assertEqual(job_env["TMPDIR"], r"C:\dev\test\.conduit-tmp\job-test")
        self.assertTrue(parent_env["PATH"].startswith(r"c:/DEV/CONDUIT/.VENV/Scripts/"))
        self.assertIn("VIRTUAL_ENV", parent_env)
        self.assertNotIn("TMPDIR", parent_env)

    def test_build_job_env_removes_unrelated_virtual_env(self):
        with patch.dict(
            os.environ,
            {"PATH": r"C:\Tools", "VIRTUAL_ENV": r"C:\dev\kairos\.venv"},
            clear=True,
        ), patch.object(conduit.sys, "prefix", r"C:\dev\conduit\.venv"):
            job_env = conduit.build_job_env(Path(r"C:\dev\test\.conduit-tmp\job-test"))
        self.assertNotIn("VIRTUAL_ENV", job_env)

    def test_ping(self):
        with self.assertLogs(conduit.logger, level="INFO") as logs:
            self.assertEqual(conduit.handle_text(conduit.PING), conduit.PONG)
        self.assertIn("PING PONG", logs.output[0])

    def test_instruction_json_base64_round_trip(self):
        instruction = """日本語
C:\\dev\\kairos
C:\\dev\\conduit\\.venv\\Scripts
{"a":"b"}
"hello"
'x'
`code`
multiple lines
&amp; &lt; & < >"""
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(
                conduit.WORKSPACES,
                {"test": self.workspace_config(workspace)},
                clear=True,
            ):
                job = conduit.parse_job(self.make_job(
                    instruction, job_id="round-trip"
                ))
        self.assertEqual(job["instruction"], instruction)
        self.assertNotIn("instruction_base64", job)

    def test_invalid_json_base64_jobs_are_rejected(self):
        cases = [
            ("invalid JSON", "invalid JSON", "not JSON"),
            ("text wire", "invalid JSON", "CONDUIT-JOB\njob_id: one"),
            ("wrong fields", "invalid fields", json.dumps({
                "job_id": "one", "workspace": "test", "instruction": "plain"
            })),
            ("extra field", "invalid fields", json.dumps({
                "job_id": "one",
                "workspace": "test",
                "instruction_base64": "dGVzdA==",
                "extra": True,
            })),
            ("empty job ID", "invalid fields", self.make_job(job_id="")),
            ("unknown workspace", "unknown workspace", self.make_job(workspace="unknown")),
            ("invalid Base64", "invalid instruction Base64", json.dumps({
                "job_id": "one",
                "workspace": "test",
                "instruction_base64": "not base64!",
            })),
            ("invalid UTF-8", "invalid instruction UTF-8", json.dumps({
                "job_id": "one",
                "workspace": "test",
                "instruction_base64": base64.b64encode(b"\xff\xfe").decode("ascii"),
            })),
            ("empty instruction", "empty instruction", self.make_job(instruction="")),
            ("whitespace instruction", "empty instruction", self.make_job(
                instruction=" \n\t"
            )),
        ]
        with tempfile.TemporaryDirectory(dir=".") as workspace, patch.dict(
            conduit.WORKSPACES,
            {"test": self.workspace_config(workspace)},
            clear=True,
        ):
            for label, expected, message in cases:
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError, expected
                ):
                    conduit.parse_job(message)

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
        job = self.make_job(job_id="conduit-e2e-001")
        attribution = "\n*使用して送信されました* <@U0C4T02QR9A>"
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(0, "done", "")
            ):
                attributed = conduit.remove_chatgpt_attribution(job + attribution)
                self.assertEqual(conduit.handle_text(attributed), "done")

    def test_unknown_workspace_is_rejected(self):
        with self.assertLogs(conduit.logger, level="ERROR") as logs:
            response = conduit.handle_text(self.make_job(
                job_id="bad-1", workspace="unknown"
            ))
        self.assertEqual(response, "INVALID_JOB: unknown workspace")
        self.assertIn("Job parse/validation error", logs.output[0])

    def test_extra_json_field_is_rejected_without_running_codex(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(
                conduit.WORKSPACES, {"test": self.workspace_config(workspace)}
            ), patch.object(conduit, "run_job") as run_job:
                response = conduit.handle_text(json.dumps({
                    "job_id": "bad-2",
                    "workspace": "test",
                    "instruction_base64": "dGVzdA==",
                    "extra": True,
                }))
        self.assertEqual(response, "INVALID_JOB: invalid fields")
        run_job.assert_not_called()

    def test_upload_schema_valid_and_job_schema_stays_strict(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace, patch.dict(
            conduit.WORKSPACES,
            {"test": self.workspace_config(workspace)},
            clear=True,
        ):
            upload = conduit.parse_upload(json.loads(self.make_upload()))
            self.assertEqual(upload["operation"], "upload")
            with self.assertRaisesRegex(ValueError, "invalid fields"):
                conduit.parse_job_object(json.loads(self.make_job()) | {"operation": "upload"})

    def test_upload_path_list_rules(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace, patch.dict(
            conduit.WORKSPACES,
            {"test": self.workspace_config(workspace)},
            clear=True,
        ):
            for paths, error in (
                ([], "invalid paths"),
                (["a", "a"], "duplicate paths"),
                ([r"tests\test_one.py"], "backslash path"),
            ):
                with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, error):
                    conduit.parse_upload(json.loads(self.make_upload(paths)))

    def test_operation_dispatch_rejects_upload_without_running_codex(self):
        with patch("conduit.run_job") as run_job:
            result = conduit.handle_text(json.dumps({
                "operation": "download",
                "job_id": "job-1",
                "workspace": "test",
                "paths": ["one.txt"],
            }))
        self.assertEqual(result, "UPLOAD_ERROR: invalid fields")
        run_job.assert_not_called()

    def test_upload_path_prevalidation_rejects_unsafe_and_non_files(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace, tempfile.TemporaryDirectory(
            dir="."
        ) as outside:
            root = Path(workspace)
            (root / "directory").mkdir()
            (Path(outside) / "outside.txt").write_text("outside", encoding="utf-8")
            cases = [
                (str((root / "absolute.txt").resolve()), "invalid path"),
                ("../outside.txt", "invalid path"),
                ("missing.txt", "missing path"),
                ("directory", "not a file"),
            ]
            for relative, error in cases:
                with self.subTest(path=relative), self.assertRaisesRegex(ValueError, error):
                    conduit.validate_upload_paths(str(root), [relative])

            link = root / "escape.txt"
            try:
                link.symlink_to(Path(outside) / "outside.txt")
            except OSError:
                pass
            else:
                with self.assertRaisesRegex(ValueError, "path outside workspace"):
                    conduit.validate_upload_paths(str(root), ["escape.txt"])

    def test_all_paths_validate_before_drive_side_effect(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            root = Path(workspace)
            (root / "valid.txt").write_text("ok", encoding="utf-8")
            with patch.dict(
                conduit.WORKSPACES,
                {"test": self.workspace_config(workspace)},
                clear=True,
            ), patch("conduit.load_drive_config") as load_config, patch(
                "conduit.upload_files"
            ) as upload:
                result = conduit.handle_text(self.make_upload(["valid.txt", "missing.txt"]))
            self.assertIn("missing path: missing.txt", result)
            load_config.assert_not_called()
            upload.assert_not_called()

    @staticmethod
    def fake_drive(existing=None, folder=None):
        service = MagicMock()
        files = service.files.return_value
        list_request = MagicMock()
        list_request.execute.return_value = {"files": existing or []}
        files.list.return_value = list_request
        folder_request = MagicMock()
        folder_request.execute.return_value = folder or {
            "id": "folder-id", "webViewLink": "https://drive/folder-id"
        }
        files.create.return_value = folder_request
        return service

    def test_existing_job_folder_rejects_before_create_or_upload(self):
        service = self.fake_drive(existing=[{"id": "existing"}])
        with self.assertRaisesRegex(ValueError, "job folder already exists"):
            drive_store.upload_files(
                {"jobs_folder_id": "parent"}, "job-1", [], service=service
            )
        service.files.return_value.create.assert_not_called()

    def test_sequential_upload_uses_relative_path_as_drive_name(self):
        service = self.fake_drive()
        files_api = service.files.return_value
        folder_request = files_api.create.return_value
        upload_one = MagicMock()
        upload_one.execute.return_value = {"id": "one"}
        upload_two = MagicMock()
        upload_two.execute.return_value = {"id": "two"}
        files_api.create.side_effect = [folder_request, upload_one, upload_two]
        selected = [(Path("one.py"), "one.py"), (Path("two.py"), "tests/two.py")]
        with patch("drive_store._media_file_upload", side_effect=["media-1", "media-2"]):
            url = drive_store.upload_files(
                {"jobs_folder_id": "parent"}, "job-1", selected, service=service
            )
        self.assertEqual(url, "https://drive/folder-id")
        self.assertEqual(
            [item.kwargs["body"]["name"] for item in files_api.create.call_args_list[1:]],
            ["one.py", "tests/two.py"],
        )
        self.assertEqual(
            [item.kwargs["media_body"] for item in files_api.create.call_args_list[1:]],
            ["media-1", "media-2"],
        )

    def test_upload_success_result_and_workspace_callback(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            Path(workspace, "one.txt").write_text("one", encoding="utf-8")
            with patch.dict(
                conduit.WORKSPACES,
                {"test": self.workspace_config(workspace)},
                clear=True,
            ), patch("conduit.load_drive_config", return_value={}), patch(
                "conduit.upload_files", return_value="https://drive/job"
            ) as upload, patch("conduit.run_job") as run_job:
                result = conduit.handle_text(self.make_upload())
            self.assertEqual(
                result, "job_id: upload-job; uploaded 1/1; folder: https://drive/job"
            )
            upload.assert_called_once()
            run_job.assert_not_called()
            self.notify.assert_called_once_with("https://chatgpt.com/c/test", result)

    def test_upload_failure_is_concise_and_callbacks(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            Path(workspace, "one.txt").write_text("one", encoding="utf-8")
            with patch.dict(
                conduit.WORKSPACES,
                {"test": self.workspace_config(workspace)},
                clear=True,
            ), patch("conduit.load_drive_config", return_value={}), patch(
                "conduit.upload_files", side_effect=RuntimeError("one.txt: denied\nmore")
            ):
                result = conduit.handle_text(self.make_upload())
            self.assertEqual(
                result, "UPLOAD_ERROR job_id=upload-job: one.txt: denied more"
            )
            self.assertEqual(len(result.splitlines()), 1)
            self.notify.assert_called_once_with("https://chatgpt.com/c/test", result)

    def test_success_returns_only_final_message(self):
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(0, "done", "diagnostic")
            ):
                with self.assertLogs(conduit.logger, level="INFO") as logs:
                    response = conduit.handle_text(self.make_job(job_id="ok-1"))
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
                conduit.handle_text(self.make_job(
                    job_id="kairos-1", workspace="kairos"
                ))
        self.notify.assert_called_once_with(kairos_url, "kairos result")

    def test_failure_limits_stderr_to_twenty_lines(self):
        stderr = "\n".join(f"line {number}" for number in range(25))
        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch.object(
                conduit, "run_job", return_value=(7, "", stderr)
            ):
                response = conduit.handle_text(self.make_job(job_id="fail-1"))
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
                response = conduit.handle_text(self.make_job(job_id="ok-3"))
        self.assertEqual(response, "done")
        run_job.assert_called_once()
        self.notify.assert_called_once_with("https://chatgpt.com/c/test", "done")
        self.assertTrue(any("ChatGPT callback failed" in line for line in logs.output))

    def test_run_job_passes_instruction_on_stdin(self):
        observed_job_tmp = None
        written_stdin = []

        class FakeStdin:
            def write(self, text):
                written_stdin.append(text)

            def close(self):
                pass

        class FakeStderr:
            def __init__(self):
                self.lines = iter(["step 1\n", "step 2\n", "step 3\n"])
                self.closed = False

            def readline(self):
                return next(self.lines, "")

            def close(self):
                self.closed = True

        class FakeProcess:
            stdin = FakeStdin()
            stdout = iter(["line 1\n", "\n", "line 2\r\n", "line 3"])
            stderr = FakeStderr()

            @staticmethod
            def wait():
                return 0

        def fake_popen(command, **kwargs):
            nonlocal observed_job_tmp
            Path(command[command.index("-o") + 1]).write_text("final", encoding="utf-8")
            self.assertEqual(command[command.index("-s") + 1], "workspace-write")
            self.assertEqual(command[-1], "-")
            self.assertIs(kwargs["stdin"], conduit.subprocess.PIPE)
            self.assertIs(kwargs["stdout"], conduit.subprocess.PIPE)
            self.assertIs(kwargs["stderr"], conduit.subprocess.PIPE)
            job_env = kwargs["env"]
            observed_job_tmp = Path(job_env["TMPDIR"])
            self.assertTrue(observed_job_tmp.is_absolute())
            self.assertTrue(observed_job_tmp.is_dir())
            self.assertEqual(observed_job_tmp.parent.name, ".conduit-tmp")
            self.assertTrue(observed_job_tmp.name.startswith("job-"))
            conduit_scripts = os.path.normcase(os.path.normpath(
                str(Path(conduit.sys.prefix) / "Scripts")
            ))
            self.assertNotIn(
                conduit_scripts,
                [os.path.normcase(os.path.normpath(item)) for item in job_env["PATH"].split(os.pathsep)],
            )
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")
            return FakeProcess()

        with tempfile.TemporaryDirectory(dir=".") as workspace:
            with patch.dict(conduit.WORKSPACES, {"test": self.workspace_config(workspace)}), patch(
                "conduit.shutil.which", return_value=r"C:\bin\codex.cmd"
            ), patch("conduit.subprocess.Popen", side_effect=fake_popen):
                job = conduit.parse_job(self.make_job(
                    "日本語 instruction", job_id="ok-2"
                ))
                with self.assertLogs(conduit.logger, level="INFO") as logs:
                    result = conduit.run_job(job)
        self.assertEqual(result, (0, "final", "step 1\nstep 2\nstep 3\n"))
        self.assertEqual(written_stdin, ["日本語 instruction"])
        self.assertTrue(FakeProcess.stderr.closed)
        self.assertIsNotNone(observed_job_tmp)
        self.assertFalse(observed_job_tmp.exists())
        stdout_logs = [line for line in logs.output if "Codex stdout:" in line]
        self.assertEqual(len(stdout_logs), 3)
        self.assertTrue(stdout_logs[0].endswith("Codex stdout: line 1"))
        self.assertTrue(stdout_logs[1].endswith("Codex stdout: line 2"))
        self.assertTrue(stdout_logs[2].endswith("Codex stdout: line 3"))
        stderr_logs = [line for line in logs.output if "Codex stderr:" in line]
        self.assertEqual(len(stderr_logs), 3)
        self.assertTrue(stderr_logs[0].endswith("Codex stderr: step 1"))
        self.assertTrue(stderr_logs[1].endswith("Codex stderr: step 2"))
        self.assertTrue(stderr_logs[2].endswith("Codex stderr: step 3"))

    def test_run_job_returns_process_exit_code_stderr_and_final_message(self):
        class FakeStdin:
            def write(self, text):
                pass

            def close(self):
                pass

        class FakeStderr:
            def __init__(self):
                self.lines = iter(["codex failed"])

            def readline(self):
                return next(self.lines, "")

            def close(self):
                pass

        class FakeProcess:
            stdin = FakeStdin()
            stdout = iter(())
            stderr = FakeStderr()

            @staticmethod
            def wait():
                return 7

        def fake_popen(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_text(
                "final from output file", encoding="utf-8"
            )
            return FakeProcess()

        with tempfile.TemporaryDirectory(dir=".") as workspace, patch.dict(
            conduit.WORKSPACES,
            {"test": self.workspace_config(workspace)},
        ), patch("conduit.shutil.which", return_value=r"C:\bin\codex.cmd"), patch(
            "conduit.subprocess.Popen", side_effect=fake_popen
        ):
            result = conduit.run_job({
                "job_id": "fail-process",
                "workspace": "test",
                "instruction": "test",
            })

        self.assertEqual(result, (7, "final from output file", "codex failed"))

    def test_run_job_cleans_job_tmp_after_subprocess_exception(self):
        observed_job_tmp = None
        temporary_paths = []

        def failing_popen(command, **kwargs):
            nonlocal observed_job_tmp
            observed_job_tmp = Path(kwargs["env"]["TMPDIR"])
            temporary_paths.append(Path(command[command.index("-o") + 1]))
            self.assertIs(kwargs["stderr"], conduit.subprocess.PIPE)
            self.assertTrue(observed_job_tmp.is_dir())
            raise RuntimeError("launch failed")

        with tempfile.TemporaryDirectory(dir=".") as workspace:
            job = {"job_id": "fail-2", "workspace": "test", "instruction": "test"}
            with patch.dict(
                conduit.WORKSPACES,
                {"test": self.workspace_config(workspace)},
            ), patch("conduit.shutil.which", return_value=r"C:\bin\codex.cmd"), patch(
                "conduit.subprocess.Popen", side_effect=failing_popen
            ):
                with self.assertRaisesRegex(RuntimeError, "launch failed"):
                    conduit.run_job(job)

        self.assertIsNotNone(observed_job_tmp)
        self.assertFalse(observed_job_tmp.exists())
        self.assertTrue(temporary_paths)
        self.assertTrue(all(not path.exists() for path in temporary_paths))


if __name__ == "__main__":
    unittest.main()
