"""
Event Sistemi
=============
Ajan → WebSocket → UI akışı için hafif event bus.
CLI modunda noop emitter kullanılır (overhead yok).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine

# Tip takma adı: async def emit(event: dict) -> None
Emitter = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


async def noop(event: dict[str, Any]) -> None:
    """CLI modunda kullanılan sessiz emitter."""
    pass


def make_queue_emitter(queue: asyncio.Queue) -> Emitter:
    """
    asyncio.Queue'ya yazan emitter döndür.
    WebSocket handler'ı bu queue'yu dinler.
    """
    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)
    return emit


def wrap(type_: str, data: dict[str, Any]) -> dict[str, Any]:
    """Standart event zarfı oluştur."""
    return {"type": type_, "ts": time.time(), "data": data}
