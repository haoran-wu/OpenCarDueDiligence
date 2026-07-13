from __future__ import annotations

import base64
from contextlib import redirect_stdout
import io
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import quickstart


EXAMPLE_ENV = """OCDD_DEPLOYMENT_MODE=local
OCDD_API_URL=http://localhost:8000
NEXT_PUBLIC_OCDD_API_URL=http://localhost:8000
OCDD_CORS_ORIGINS=http://localhost:3000
OCDD_WORKER_ENVELOPE_KEY=
OCDD_OBD_BRIDGE_TOKEN=
OCDD_LLM_PROVIDER=disabled
"""


class QuickstartEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / ".env.example").write_text(EXAMPLE_ENV, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_prepare_creates_private_random_key_without_paid_credentials(self) -> None:
        web_port, api_port, created = quickstart.prepare_environment(self.root)

        self.assertTrue(created)
        self.assertEqual((web_port, api_port), (3000, 8000))
        env_path = self.root / ".env"
        values = quickstart.env_values(env_path.read_text(encoding="utf-8"))
        self.assertEqual(len(base64.urlsafe_b64decode(values["OCDD_WORKER_ENVELOPE_KEY"])), 32)
        self.assertGreaterEqual(len(values["OCDD_OBD_BRIDGE_TOKEN"]), 32)
        self.assertEqual(values["OCDD_LLM_PROVIDER"], "disabled")
        self.assertNotIn("OPENAI_API_KEY", values)
        self.assertNotIn("ANTHROPIC_API_KEY", values)
        self.assertIn("http://127.0.0.1:3000", values["OCDD_CORS_ORIGINS"])
        if hasattr(stat, "S_IMODE"):
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)

    def test_prepare_is_idempotent_and_preserves_existing_secret(self) -> None:
        quickstart.prepare_environment(self.root)
        first_values = quickstart.env_values((self.root / ".env").read_text(encoding="utf-8"))

        _, _, created = quickstart.prepare_environment(self.root)
        second_values = quickstart.env_values((self.root / ".env").read_text(encoding="utf-8"))

        self.assertFalse(created)
        self.assertEqual(
            first_values["OCDD_WORKER_ENVELOPE_KEY"],
            second_values["OCDD_WORKER_ENVELOPE_KEY"],
        )
        self.assertEqual(
            first_values["OCDD_OBD_BRIDGE_TOKEN"],
            second_values["OCDD_OBD_BRIDGE_TOKEN"],
        )

    def test_custom_ports_keep_browser_api_and_cors_in_sync(self) -> None:
        quickstart.prepare_environment(self.root, web_port=3100, api_port=8100)
        values = quickstart.env_values((self.root / ".env").read_text(encoding="utf-8"))

        self.assertEqual(values["OCDD_WEB_PORT"], "3100")
        self.assertEqual(values["OCDD_API_PORT"], "8100")
        self.assertEqual(values["NEXT_PUBLIC_OCDD_API_URL"], "http://localhost:8100")
        self.assertIn("http://localhost:3100", values["OCDD_CORS_ORIGINS"])
        self.assertIn("http://127.0.0.1:3100", values["OCDD_CORS_ORIGINS"])

    def test_prepare_replaces_stale_remote_api_and_cors_configuration(self) -> None:
        (self.root / ".env").write_text(
            EXAMPLE_ENV
            .replace("OCDD_API_URL=http://localhost:8000", "OCDD_API_URL=https://old.example/api")
            .replace("NEXT_PUBLIC_OCDD_API_URL=http://localhost:8000", "NEXT_PUBLIC_OCDD_API_URL=https://old.example/api")
            .replace("OCDD_CORS_ORIGINS=http://localhost:3000", "OCDD_CORS_ORIGINS=https://old.example"),
            encoding="utf-8",
        )

        quickstart.prepare_environment(self.root)
        values = quickstart.env_values((self.root / ".env").read_text(encoding="utf-8"))

        self.assertEqual(values["OCDD_API_URL"], "http://localhost:8000")
        self.assertEqual(values["NEXT_PUBLIC_OCDD_API_URL"], "http://localhost:8000")
        self.assertEqual(
            values["OCDD_CORS_ORIGINS"],
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        self.assertNotIn("old.example", (self.root / ".env").read_text(encoding="utf-8"))

    def test_invalid_existing_worker_key_fails_closed(self) -> None:
        (self.root / ".env").write_text(
            EXAMPLE_ENV.replace("OCDD_WORKER_ENVELOPE_KEY=", "OCDD_WORKER_ENVELOPE_KEY=not-a-key"),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(quickstart.QuickstartError, "URL-safe base64"):
            quickstart.prepare_environment(self.root)


class QuickstartCommandTests(unittest.TestCase):
    @mock.patch.object(quickstart, "wait_for_stack")
    @mock.patch.object(quickstart, "require_docker")
    @mock.patch.object(quickstart, "run_command")
    @mock.patch.object(quickstart.webbrowser, "open")
    def test_start_uses_compose_wait_without_opening_when_disabled(
        self,
        browser_open: mock.Mock,
        run_command: mock.Mock,
        require_docker: mock.Mock,
        wait_for_stack: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text(EXAMPLE_ENV, encoding="utf-8")
            run_command.return_value = subprocess.CompletedProcess([], 0)

            with redirect_stdout(io.StringIO()):
                quickstart.start(root, wait_timeout=123, open_browser=False)

        require_docker.assert_called_once_with(root)
        run_command.assert_called_once_with(
            quickstart.compose_command(
                "up",
                "--detach",
                "--remove-orphans",
                "--build",
                "--wait",
                "--wait-timeout",
                "123",
                repo_root=root,
            ),
            repo_root=root,
        )
        wait_for_stack.assert_called_once_with(3000, 8000, 123)
        browser_open.assert_not_called()

    @mock.patch.object(quickstart, "require_docker")
    @mock.patch.object(quickstart, "run_command")
    def test_stop_deletes_volumes_only_when_explicit(
        self,
        run_command: mock.Mock,
        require_docker: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_command.side_effect = [
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ]
            with redirect_stdout(io.StringIO()):
                quickstart.stop(root, delete_data=True)

        require_docker.assert_called_once_with(root)
        self.assertEqual(
            run_command.call_args_list,
            [
                mock.call(
                    quickstart.compose_command(
                        "down",
                        "--remove-orphans",
                        "--volumes",
                        repo_root=root,
                    ),
                    repo_root=root,
                ),
                mock.call(
                    ["docker", "volume", "inspect", "opencarduediligence_valkey-data"],
                    repo_root=root,
                    check=False,
                    capture_output=True,
                ),
                mock.call(
                    ["docker", "volume", "rm", "opencarduediligence_valkey-data"],
                    repo_root=root,
                    capture_output=True,
                ),
            ],
        )

    @mock.patch.object(quickstart.subprocess, "run")
    def test_run_command_strips_app_and_compose_overrides(self, subprocess_run: mock.Mock) -> None:
        subprocess_run.return_value = subprocess.CompletedProcess([], 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict(
                quickstart.os.environ,
                {
                    "COMPOSE_FILE": "/tmp/hostile-compose.yml",
                    "COMPOSE_PROJECT_NAME": "wrong-project",
                    "OCDD_WORKER_ENVELOPE_KEY": "weak-shell-key",
                    "OCDD_CORS_ORIGINS": "https://remote.example",
                    "NEXT_PUBLIC_OCDD_API_URL": "https://remote.example/api",
                    "DOCKER_CONTEXT": "desktop-linux",
                },
                clear=False,
            ):
                command = quickstart.compose_command("config", "--quiet", repo_root=root)
                quickstart.run_command(command, repo_root=root)

        called_command = subprocess_run.call_args.args[0]
        called_environment = subprocess_run.call_args.kwargs["env"]
        self.assertIn(str(root / "docker-compose.yml"), called_command)
        self.assertIn(str(root / ".env"), called_command)
        self.assertNotIn("COMPOSE_FILE", called_environment)
        self.assertNotIn("COMPOSE_PROJECT_NAME", called_environment)
        self.assertNotIn("OCDD_WORKER_ENVELOPE_KEY", called_environment)
        self.assertNotIn("OCDD_CORS_ORIGINS", called_environment)
        self.assertNotIn("NEXT_PUBLIC_OCDD_API_URL", called_environment)
        self.assertEqual(called_environment["DOCKER_CONTEXT"], "desktop-linux")


if __name__ == "__main__":
    unittest.main()
