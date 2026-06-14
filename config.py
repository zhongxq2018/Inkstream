"""应用配置：环境变量 > config.json > 默认值。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

DEFAULT_INFERENCE_WORKERS = 2
DEFAULT_INFERENCE_QUEUE_TIMEOUT = 120
MAX_INFERENCE_WORKERS = 16
MEM_GB_PER_WORKER = 2.5


@dataclass(frozen=True)
class AppConfig:
    inference_workers: int = DEFAULT_INFERENCE_WORKERS
    inference_queue_timeout: int = DEFAULT_INFERENCE_QUEUE_TIMEOUT


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def load_config() -> AppConfig:
    data: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            raw = json.load(fh)
            if isinstance(raw, dict):
                data = raw

    workers = _coerce_int(
        os.environ.get("INFERENCE_WORKERS", data.get("inference_workers", DEFAULT_INFERENCE_WORKERS)),
        DEFAULT_INFERENCE_WORKERS,
    )
    queue_timeout = _coerce_int(
        os.environ.get(
            "INFERENCE_QUEUE_TIMEOUT",
            data.get("inference_queue_timeout", DEFAULT_INFERENCE_QUEUE_TIMEOUT),
        ),
        DEFAULT_INFERENCE_QUEUE_TIMEOUT,
    )

    workers = max(1, min(MAX_INFERENCE_WORKERS, workers))
    queue_timeout = max(1, queue_timeout)

    return AppConfig(inference_workers=workers, inference_queue_timeout=queue_timeout)


def estimate_memory_gb(workers: int) -> float:
    return workers * MEM_GB_PER_WORKER


def config_source_label() -> str:
    if os.environ.get("INFERENCE_WORKERS") or os.environ.get("INFERENCE_QUEUE_TIMEOUT"):
        return "环境变量"
    if CONFIG_PATH.exists():
        return "config.json"
    return "内置默认"
