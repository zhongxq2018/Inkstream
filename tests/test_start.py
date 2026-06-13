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
    @patch("start.urllib.request.urlopen")
    def test_wait_for_health_ok(self, mock_urlopen: MagicMock) -> None:
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        mock_urlopen.return_value = response

        start.wait_for_health()

        mock_urlopen.assert_called_once()

    @patch("start.time.sleep")
    @patch("start.time.time")
    @patch("start.urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_wait_for_health_timeout(
        self,
        mock_urlopen: MagicMock,
        mock_time: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        # deadline=600；先进入循环一次，再超时退出
        mock_time.side_effect = [0, 0, start.STARTUP_TIMEOUT_SEC + 1]

        with self.assertRaises(TimeoutError):
            start.wait_for_health()

        mock_urlopen.assert_called_once()
        mock_sleep.assert_called_once_with(1)


class TestMain(unittest.TestCase):
    @patch("start.webbrowser.open")
    @patch("start.wait_for_health")
    @patch("start.subprocess.Popen")
    @patch("start.model_is_ready", return_value=True)
    @patch("start.install_dependencies")
    @patch("start.ensure_venv", return_value=Path("fake/python.exe"))
    def test_main_happy_path(
        self,
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
        mock_install.assert_called_once_with(Path("fake/python.exe"))
        mock_model_ready.assert_called_once()
        mock_popen.assert_called_once()
        mock_wait.assert_called_once()
        mock_browser.assert_called_once_with(start.APP_URL)

    @patch("start.download_model")
    @patch("start.model_is_ready", return_value=False)
    @patch("start.install_dependencies")
    @patch("start.ensure_venv", return_value=Path("fake/python.exe"))
    def test_main_download_then_fail(
        self,
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
    def test_main_keyboard_interrupt(
        self,
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


if __name__ == "__main__":
    unittest.main()
