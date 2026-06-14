"""config.py 单元测试。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


class TestLoadConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_defaults_without_file(self) -> None:
        with patch.object(config, "CONFIG_PATH", Path("/nonexistent/config.json")):
            cfg = config.load_config()
        self.assertEqual(cfg.inference_workers, 2)
        self.assertEqual(cfg.inference_queue_timeout, 120)

    def test_reads_config_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"inference_workers": 4, "inference_queue_timeout": 60}),
                encoding="utf-8",
            )
            with patch.object(config, "CONFIG_PATH", path):
                cfg = config.load_config()
        self.assertEqual(cfg.inference_workers, 4)
        self.assertEqual(cfg.inference_queue_timeout, 60)

    def test_env_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"inference_workers": 4}), encoding="utf-8")
            os.environ["INFERENCE_WORKERS"] = "6"
            with patch.object(config, "CONFIG_PATH", path):
                cfg = config.load_config()
        self.assertEqual(cfg.inference_workers, 6)

    def test_clamps_workers(self) -> None:
        os.environ["INFERENCE_WORKERS"] = "99"
        with patch.object(config, "CONFIG_PATH", Path("/nonexistent/config.json")):
            cfg = config.load_config()
        self.assertEqual(cfg.inference_workers, config.MAX_INFERENCE_WORKERS)

    def test_estimate_memory_gb(self) -> None:
        self.assertEqual(config.estimate_memory_gb(2), 5.0)


if __name__ == "__main__":
    unittest.main()
