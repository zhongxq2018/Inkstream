"""验证两路 /chat/stream 可同时开始（不串行等待）。"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8000"


def _post_stream(prompt: str, out: dict, key: str) -> None:
    body = json.dumps({"prompt": prompt, "max_new_tokens": 64}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/chat/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started_at = None
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            data = json.loads(payload)
            if data.get("event") == "started" and started_at is None:
                started_at = time.time()
            if data.get("text"):
                break
    out[key] = started_at


def main() -> int:
    health = json.loads(urllib.request.urlopen(f"{BASE}/health", timeout=10).read())
    workers = health.get("inference_workers")
    if workers != 2:
        print(f"FAIL: expected inference_workers=2, got {workers}")
        return 1

    out: dict[str, float | None] = {}
    t0 = time.time()
    threads = [
        threading.Thread(target=_post_stream, args=("简述神经网络", out, "a")),
        threading.Thread(target=_post_stream, args=("简述量子计算", out, "b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    a, b = out.get("a"), out.get("b")
    if a is None or b is None:
        print(f"FAIL: missing started event a={a} b={b}")
        return 1

    gap = abs(a - b)
    print(f"OK: both streams started (gap={gap:.2f}s, workers={workers})")
    if gap > 30:
        print("WARN: large gap suggests serial execution")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
