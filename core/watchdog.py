"""
Watchdog — Arka Plan Ajan İzleyicisi
======================================
Küçük, hafif bir izleyici: ajan akışlarını takip eder.
Takılma (stall) veya tekrar (repetition) tespit edildiğinde görevi iptal eder.

Kullanım:
    watchdog = Watchdog(emit=emit_fn)
    wrapped_emit = watchdog.make_emit_wrapper(base_emit)
    try:
        result = await watchdog.guard(task_id, agent_type, agent.execute(task, emit=wrapped_emit))
    except asyncio.CancelledError:
        result = ...  # watchdog killed it
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable

from core.events import Emitter, noop, wrap

# ─── Sabitleri ─────────────────────────────────────────────────────────────────

STALL_TIMEOUT_S   = 90    # Saniye — bu kadar yeni token gelmezse takılı sayılır
REPEAT_WINDOW     = 600   # Karakter — tekrar tespiti için pencere
REPEAT_MIN_LEN    = 30    # En az bu kadar karakter olmalı ki kontrol edilsin
MONITOR_TICK_S    = 15    # Her 15 saniyede bir stall/repeat kontrolü


class WatchdogCancelled(Exception):
    """Watchdog tarafından iptal edildi."""
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Watchdog:
    """
    Bir ajanın execute() coroutine'ini yan yana izler.
    Token akışını takip eder — çok uzun süre duraklanırsa veya çıktı
    kendini tekrar ediyorsa görevi iptal eder.
    """

    def __init__(
        self,
        emit:       Emitter = noop,
        timeout_s:  int     = STALL_TIMEOUT_S,
    ) -> None:
        self._emit       = emit
        self._timeout    = timeout_s
        self._last_token = time.monotonic()
        self._buf        = ""          # son token'lar için ring buffer
        self._cancelled  = False
        self._reason     = ""

    # ── Token izleme ────────────────────────────────────────────────────────

    def touch(self) -> None:
        """Herhangi bir aktivite olduğunda çağrılır."""
        self._last_token = time.monotonic()

    def feed(self, chunk: str) -> None:
        """Yeni token chunk'ını işle."""
        if not chunk:
            return
        self._buf = (self._buf + chunk)[-REPEAT_WINDOW * 3:]
        self.touch()

    # ── Tekrar tespiti ───────────────────────────────────────────────────────

    def _is_repeating(self) -> bool:
        """Son pencerede belirgin bir tekrar var mı?"""
        buf = self._buf
        if len(buf) < REPEAT_WINDOW:
            return False

        # Son 200 karakteri al ve öncekinde ara
        tail = buf[-200:].strip()
        head = buf[:-200]

        if len(tail) < REPEAT_MIN_LEN or not head:
            return False

        # Normalize whitespace
        tail_n = re.sub(r"\s+", " ", tail)
        head_n = re.sub(r"\s+", " ", head)

        # Tail'in ilk 60 karakteri head'de 2+ kez görünüyorsa tekrar sayılır
        snippet = tail_n[:60]
        if len(snippet) < 20:
            return False

        count = head_n.count(snippet)
        return count >= 3

    # ── Emit sarmalayıcı ─────────────────────────────────────────────────────

    def make_emit_wrapper(self, base_emit: Emitter) -> Emitter:
        """
        base_emit'i saran wrapper.
        Her stream chunk'ında watchdog'u besler.
        """
        async def _wrapped(event: dict) -> None:
            if event.get("type") in ("task.stream", "supervisor.stream", "agent.stream"):
                chunk = (event.get("data") or {}).get("chunk", "")
                if chunk:
                    self.feed(chunk)
            await base_emit(event)
        return _wrapped

    # ── İzleme döngüsü ──────────────────────────────────────────────────────

    async def _monitor_loop(
        self,
        inner_task: asyncio.Task,
        task_id:    str,
        agent_type: str,
    ) -> None:
        """Arka planda çalışır; stall veya tekrar tespit ederse iptal eder."""
        while not inner_task.done() and not self._cancelled:
            await asyncio.sleep(MONITOR_TICK_S)
            if inner_task.done():
                break

            since_last = time.monotonic() - self._last_token

            if since_last >= self._timeout:
                self._cancelled = True
                self._reason    = f"No token for {since_last:.0f}s"
                inner_task.cancel()
                await self._emit(wrap("watchdog.timeout", {
                    "task_id":    task_id,
                    "agent_type": agent_type,
                    "stall_s":    round(since_last, 1),
                    "reason":     self._reason,
                }))
                return

            if self._is_repeating():
                self._cancelled = True
                self._reason    = "Output repetition detected"
                inner_task.cancel()
                await self._emit(wrap("watchdog.repetition", {
                    "task_id":    task_id,
                    "agent_type": agent_type,
                    "reason":     self._reason,
                }))
                return

    # ── Ana guard metodu ─────────────────────────────────────────────────────

    async def guard(
        self,
        task_id:    str,
        agent_type: str,
        coro:       Awaitable[Any],
    ) -> Any:
        """
        Coroutine'i izleyerek çalıştır.
        Watchdog iptal ederse asyncio.CancelledError yükseltilir.
        """
        self._last_token = time.monotonic()
        self._cancelled  = False

        inner_task = asyncio.create_task(coro)
        monitor    = asyncio.create_task(
            self._monitor_loop(inner_task, task_id, agent_type)
        )

        try:
            result = await inner_task
            return result
        except asyncio.CancelledError:
            if self._cancelled:
                # Watchdog tarafından iptal edildi — daha açıklayıcı hata
                raise WatchdogCancelled(self._reason)
            raise
        finally:
            monitor.cancel()
            try:
                await monitor
            except (asyncio.CancelledError, Exception):
                pass
