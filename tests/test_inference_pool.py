"""inference_pool.py 单元测试（不加载真实模型）。"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inference_pool import InferencePool, InferenceSlot  # noqa: E402


def _make_slot(index: int = 0) -> InferenceSlot:
    return InferenceSlot(index=index, tokenizer=MagicMock(), model=MagicMock())


class TestInferencePool(unittest.TestCase):
    def test_stats_initial(self) -> None:
        pool = InferencePool([_make_slot(), _make_slot(1)], queue_timeout=5.0)
        stats = pool.stats()
        self.assertEqual(stats["inference_workers"], 2)
        self.assertEqual(stats["inference_active"], 0)
        self.assertEqual(stats["inference_queued"], 0)

    def test_acquire_release_roundtrip(self) -> None:
        async def run() -> None:
            pool = InferencePool([_make_slot()], queue_timeout=1.0)
            slot, position = await pool.acquire()
            self.assertEqual(position, 0)
            self.assertEqual(pool.stats()["inference_active"], 1)
            await pool.release(slot)
            self.assertEqual(pool.stats()["inference_active"], 0)

        asyncio.run(run())

    def test_second_acquire_waits_until_release(self) -> None:
        async def run() -> None:
            pool = InferencePool([_make_slot()], queue_timeout=2.0)
            slot1, _ = await pool.acquire()
            order: list[str] = []

            async def waiter() -> None:
                slot2, position = await pool.acquire()
                order.append("got")
                await pool.release(slot2)

            task = asyncio.create_task(waiter())
            await asyncio.sleep(0.05)
            order.append("before_release")
            await pool.release(slot1)
            await task
            self.assertEqual(order, ["before_release", "got"])

        asyncio.run(run())

    @patch("inference_pool.load_model")
    def test_create_loads_n_slots(self, mock_load: MagicMock) -> None:
        mock_load.return_value = (MagicMock(), MagicMock())
        pool = InferencePool.create("/fake", "cpu", workers=3, queue_timeout=10.0)
        self.assertEqual(pool.worker_count, 3)
        self.assertEqual(mock_load.call_count, 3)


if __name__ == "__main__":
    unittest.main()
