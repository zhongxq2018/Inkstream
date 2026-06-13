"""start.py 启动逻辑单元测试（mock 隔离 pip / 下载 / 服务）。"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import start  # noqa: E402

VALID_HEALTH = b'{"status":"ok","model":"models/Qwen/Qwen3.5-0.8B","port":8000}'


def _mock_health_response(payload: bytes = VALID_HEALTH, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.read.return_value = payload
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestVenvPaths(unittest.TestCase):
    @patch("start.sys.platform", "win32")
    def test_venv_python_win32(self) -> None:
        self.assertEqual(
            start._venv_python(),
            start.VENV_DIR / "Scripts" / "python.exe",
        )

    @patch("start.sys.platform", "linux")
    def test_venv_python_unix(self) -> None:
        self.assertEqual(
            start._venv_python(),
            start.VENV_DIR / "bin" / "python",
        )


class TestEnsureVenv(unittest.TestCase):
    @patch("start.venv.create")
    @patch("start._venv_python")
    def test_ensure_venv_skips_create(self, mock_venv_python: MagicMock, mock_create: MagicMock) -> None:
        python = MagicMock()
        python.exists.return_value = True
        mock_venv_python.return_value = python

        result = start.ensure_venv()

        self.assertIs(result, python)
        mock_create.assert_not_called()

    @patch("start.venv.create")
    @patch("start._venv_python")
    def test_ensure_venv_creates(self, mock_venv_python: MagicMock, mock_create: MagicMock) -> None:
        python = MagicMock()
        python.exists.return_value = False
        mock_venv_python.return_value = python

        result = start.ensure_venv()

        self.assertIs(result, python)
        mock_create.assert_called_once_with(start.VENV_DIR, with_pip=True)


class TestInstallDependencies(unittest.TestCase):
    @patch("start.REQUIREMENTS")
    def test_install_dependencies_missing_file(self, mock_requirements: MagicMock) -> None:
        mock_requirements.exists.return_value = False
        mock_requirements.__str__ = lambda self: "/missing/requirements.txt"

        with self.assertRaises(FileNotFoundError):
            start.install_dependencies(Path("fake/python.exe"))


class TestModelIsReady(unittest.TestCase):
    @patch("start.subprocess.run")
    def test_model_is_ready_true(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="models/Qwen/Qwen3.5-0.8B\n",
            stderr="",
        )

        self.assertTrue(start.model_is_ready(Path("fake/python.exe")))
        mock_run.assert_called_once()

    @patch("start.subprocess.run")
    def test_model_is_ready_false(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )

        self.assertFalse(start.model_is_ready(Path("fake/python.exe")))


class TestWaitForHealth(unittest.TestCase):
    @patch("start.service_is_running", return_value=True)
    def test_wait_for_health_ok(self, mock_running: MagicMock) -> None:
        start.wait_for_health()

        mock_running.assert_called_once()

    @patch("start.time.sleep")
    @patch("start.time.time")
    @patch("start.service_is_running", return_value=False)
    def test_wait_for_health_timeout(
        self,
        mock_running: MagicMock,
        mock_time: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_time.side_effect = [0, 0, start.STARTUP_TIMEOUT_SEC + 1]

        with self.assertRaises(TimeoutError):
            start.wait_for_health()

        mock_running.assert_called()
        mock_sleep.assert_called_once_with(1)

    @patch("start.time.sleep")
    @patch("start.time.time", return_value=0)
    @patch("start.service_is_running", return_value=False)
    def test_wait_for_health_proc_exited(
        self,
        mock_running: MagicMock,
        mock_time: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = 1

        with self.assertRaises(RuntimeError) as ctx:
            start.wait_for_health(proc)

        self.assertIn("服务进程已退出", str(ctx.exception))
        mock_running.assert_not_called()
        mock_sleep.assert_not_called()


class TestParseHealth(unittest.TestCase):
    def test_parse_valid_payload(self) -> None:
        data = start._parse_health_payload(VALID_HEALTH)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["port"], 8000)

    def test_parse_rejects_wrong_status(self) -> None:
        payload = b'{"status":"degraded","model":"x","port":8000}'
        self.assertIsNone(start._parse_health_payload(payload))

    def test_parse_rejects_missing_model(self) -> None:
        payload = b'{"status":"ok","port":8000}'
        self.assertIsNone(start._parse_health_payload(payload))

    def test_parse_rejects_wrong_port(self) -> None:
        payload = b'{"status":"ok","model":"x","port":9000}'
        self.assertIsNone(start._parse_health_payload(payload))


class TestServiceIsRunning(unittest.TestCase):
    @patch("start.urllib.request.urlopen")
    def test_service_is_running_true(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_health_response()

        self.assertTrue(start.service_is_running())

    @patch("start.urllib.request.urlopen")
    def test_service_is_running_false_on_generic_health(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_health_response(b'{"status":"ok"}')

        self.assertFalse(start.service_is_running())

    @patch("start.urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_service_is_running_false(self, mock_urlopen: MagicMock) -> None:
        self.assertFalse(start.service_is_running())


class TestPortChecks(unittest.TestCase):
    @patch("start.port_is_in_use", return_value=False)
    def test_ensure_port_free_when_unused(self, mock_in_use: MagicMock) -> None:
        start.ensure_port_free_for_startup()
        mock_in_use.assert_called_once()

    @patch("start.describe_port_blocker", return_value="other.exe (PID 1234)")
    @patch("start.port_is_in_use", return_value=True)
    def test_ensure_port_free_raises_when_blocked(
        self,
        mock_in_use: MagicMock,
        mock_describe: MagicMock,
    ) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            start.ensure_port_free_for_startup()

        self.assertIn("端口 8000", str(ctx.exception))
        self.assertIn("other.exe", str(ctx.exception))


class TestMain(unittest.TestCase):
    @patch("start.webbrowser.open")
    @patch("start.service_is_running", return_value=True)
    def test_main_already_running(
        self,
        mock_running: MagicMock,
        mock_browser: MagicMock,
    ) -> None:
        self.assertEqual(start.main(), 0)

        mock_running.assert_called_once()
        mock_browser.assert_called_once_with(start.APP_URL)

    @patch("start.webbrowser.open")
    @patch("start.wait_for_health")
    @patch("start.subprocess.Popen")
    @patch("start.model_is_ready", return_value=True)
    @patch("start.install_dependencies")
    @patch("start.ensure_venv", return_value=Path("fake/python.exe"))
    @patch("start.ensure_port_free_for_startup")
    @patch("start.service_is_running", return_value=False)
    def test_main_happy_path(
        self,
        mock_running: MagicMock,
        mock_port_free: MagicMock,
        mock_ensure_venv: MagicMock,
        mock_install: MagicMock,
        mock_model_ready: MagicMock,
        mock_popen: MagicMock,
        mock_wait: MagicMock,
        mock_browser: MagicMock,
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        self.assertEqual(start.main(), 0)

        mock_ensure_venv.assert_called_once()
        mock_port_free.assert_called_once()
        mock_install.assert_called_once_with(Path("fake/python.exe"))
        mock_model_ready.assert_called_once()
        mock_popen.assert_called_once()
        mock_wait.assert_called_once()
        mock_browser.assert_called_once_with(start.APP_URL)

    @patch("start.download_model")
    @patch("start.model_is_ready", return_value=False)
    @patch("start.install_dependencies")
    @patch("start.ensure_venv", return_value=Path("fake/python.exe"))
    @patch("start.ensure_port_free_for_startup")
    @patch("start.service_is_running", return_value=False)
    def test_main_download_then_fail(
        self,
        _mock_running: MagicMock,
        _mock_port_free: MagicMock,
        mock_ensure_venv: MagicMock,
        mock_install: MagicMock,
        mock_model_ready: MagicMock,
        mock_download: MagicMock,
    ) -> None:
        self.assertEqual(start.main(), 1)

        mock_download.assert_called_once_with(Path("fake/python.exe"))
        self.assertEqual(mock_model_ready.call_count, 2)

    @patch("start.wait_for_health", side_effect=KeyboardInterrupt)
    @patch("start.subprocess.Popen")
    @patch("start.model_is_ready", return_value=True)
    @patch("start.install_dependencies")
    @patch("start.ensure_venv", return_value=Path("fake/python.exe"))
    @patch("start.ensure_port_free_for_startup")
    @patch("start.service_is_running", return_value=False)
    def test_main_keyboard_interrupt(
        self,
        _mock_running: MagicMock,
        _mock_port_free: MagicMock,
        mock_ensure_venv: MagicMock,
        mock_install: MagicMock,
        mock_model_ready: MagicMock,
        mock_popen: MagicMock,
        mock_wait: MagicMock,
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        self.assertEqual(start.main(), 0)

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=10)

    @patch("start.ensure_port_free_for_startup", side_effect=RuntimeError("端口 8000 已被其他程序占用"))
    @patch("start.service_is_running", return_value=False)
    def test_main_port_blocked(
        self,
        _mock_running: MagicMock,
        _mock_port_free: MagicMock,
    ) -> None:
        self.assertEqual(start.main(), 1)


if __name__ == "__main__":
    unittest.main()
