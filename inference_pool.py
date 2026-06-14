"""多副本模型推理池：支持可配置并行路数。"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event

from infer import chat_messages, load_model, stream_chat_messages


class InferencePoolBusyError(TimeoutError):
    """等待空闲推理副本超时。"""


@dataclass
class InferenceSlot:
    index: int
    tokenizer: object
    model: object

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool = False,
        max_new_tokens: int = 512,
    ) -> str:
        return chat_messages(
            self.tokenizer,
            self.model,
            messages,
            enable_thinking=enable_thinking,
            max_new_tokens=max_new_tokens,
        )

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        enable_thinking: bool = False,
        max_new_tokens: int = 512,
        cancel_event: Event | None = None,
    ) -> Iterator[str]:
        yield from stream_chat_messages(
            self.tokenizer,
            self.model,
            messages,
            enable_thinking=enable_thinking,
            max_new_tokens=max_new_tokens,
            cancel_event=cancel_event,
        )


class InferencePool:
    def __init__(self, slots: list[InferenceSlot], *, queue_timeout: float) -> None:
        self._workers = len(slots)
        self._queue_timeout = queue_timeout
        self._free_slots: asyncio.Queue[InferenceSlot] = asyncio.Queue()
        for slot in slots:
            self._free_slots.put_nowait(slot)
        self._active = 0
        self._waiting_count = 0
        self._mutex = asyncio.Lock()

    @classmethod
    def create(
        cls,
        model_path: str,
        device: str,
        workers: int,
        queue_timeout: float,
    ) -> InferencePool:
        cpu_count = os.cpu_count() or 2
        if workers > cpu_count:
            print(
                f"警告: inference_workers={workers} 超过 CPU 核数 ({cpu_count})，"
                "单请求可能变慢，总吞吐未必线性提升。"
            )

        slots: list[InferenceSlot] = []
        for index in range(workers):
            print(f"正在加载推理池 slot {index + 1}/{workers} ...")
            tokenizer, model = load_model(model_path, device)
            slots.append(InferenceSlot(index=index, tokenizer=tokenizer, model=model))

        print(f"推理池就绪: {workers} 路并行")
        return cls(slots, queue_timeout=queue_timeout)

    @property
    def worker_count(self) -> int:
        return self._workers

    def stats(self) -> dict[str, int]:
        return {
            "inference_workers": self._workers,
            "inference_active": self._active,
            "inference_queued": self._waiting_count,
        }

    async def acquire(self) -> tuple[InferenceSlot, int]:
        async with self._mutex:
            self._waiting_count += 1
            position = max(0, self._active + self._waiting_count - self._workers)

        try:
            slot = await asyncio.wait_for(
                self._free_slots.get(),
                timeout=self._queue_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise InferencePoolBusyError("推理繁忙，请稍后重试") from exc
        finally:
            async with self._mutex:
                self._waiting_count -= 1

        async with self._mutex:
            self._active += 1
        return slot, position

    async def release(self, slot: InferenceSlot) -> None:
        async with self._mutex:
            self._active = max(0, self._active - 1)
        await self._free_slots.put(slot)
