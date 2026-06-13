"""start.bat 启动器静态与动态冒烟测试。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START_BAT = ROOT / "start.bat"


def _python_available() -> bool:
    for cmd in (["where", "py"], ["where", "python"]):
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            return True
    return False


class TestStartBatStatic(unittest.TestCase):
    def setUp(self) -> None:
        self.content = START_BAT.read_text(encoding="utf-8")

    def test_contains_echo_off(self) -> None:
        self.assertIn("@echo off", self.content)

    def test_changes_to_script_directory(self) -> None:
        self.assertIn('cd /d "%~dp0"', self.content)

    def test_invokes_py_launcher(self) -> None:
        self.assertIn("py -3", self.content)

    def test_invokes_python_fallback(self) -> None:
        self.assertIn("python", self.content)

    def test_runs_start_py(self) -> None:
        self.assertIn("start.py", self.content)

    def test_shows_python_missing_error(self) -> None:
        self.assertIn("未找到 Python", self.content)
        self.assertIn("Add to PATH", self.content)


class TestStartBatDynamic(unittest.TestCase):
    @unittest.skipUnless(_python_available(), "本机未找到 py 或 python，跳过动态冒烟")
    def test_bat_launches_stub_start_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "start.py").write_text(
                "import sys\nsys.exit(0)\n",
                encoding="utf-8",
            )
            shutil.copy2(START_BAT, tmp_path / "start.bat")

            result = subprocess.run(
                ["cmd", "/c", "start.bat"],
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
            )


if __name__ == "__main__":
    unittest.main()
