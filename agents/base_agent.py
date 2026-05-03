"""
Temel Ajan Sınıfı
=================
Tüm uzman ajanların miras aldığı soyut temel sınıf.

Yenilikler:
  - Streaming desteği (emit fonksiyonu varsa stream, yoksa blocking)
  - task.stream eventleri: UI'a gerçek zamanlı chunk akışı
  - Kişilik (persona) tabanlı system prompt yapısı
  - GPU devre dışıyken otomatik CPU moduna düşer (Ollama sayesinde)
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rich.console import Console


# ── <think> Filtresi (deepseek-r1, qwq vb. reasoning modeller) ──────────────

def _strip_think_blocks(text: str) -> str:
    """Blocking modda tam metinden <think>...</think> bloklarını sil."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def _filter_think_chunk(
    chunk: str,
    buf: str,
    in_think: bool,
) -> tuple[str, bool, str]:
    """
    Streaming chunk'larında <think> bloklarını filtrele.
    Returns: (visible_text, in_think_state, remaining_buf)
    """
    visible = ""
    rest    = buf + chunk

    while rest:
        if in_think:
            end = rest.find("</think>")
            if end == -1:
                # Hâlâ think bloğu içindeyiz, buffer'da tut
                return visible, True, rest
            rest     = rest[end + 8:]
            in_think = False
        else:
            start = rest.find("<think>")
            if start == -1:
                visible += rest
                return visible, False, ""
            visible += rest[:start]
            rest     = rest[start + 7:]
            in_think = True

    return visible, in_think, ""

from config import MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from core.memory import ConversationMemory
from core.models import AgentResult, AgentType, Task

if TYPE_CHECKING:
    pass

console = Console()


class BaseAgent(ABC):
    def __init__(
        self,
        agent_type: AgentType,
        memory: ConversationMemory | None = None,
    ) -> None:
        self.agent_type = agent_type
        self.memory     = memory or ConversationMemory(agent_name=agent_type.value)

        cfg = MODELS.get(agent_type.value, MODELS["fast"])
        self.llm = create_llm(
            provider    = cfg["provider"],
            model       = cfg["model"],
            temperature = cfg.get("temperature", 0.1),
        )
        self._model_label = f"{cfg['provider']}:{cfg['model']}"
        self._persona     = cfg.get("persona", "")
        self.system_prompt = self._build_system_prompt()

    # ── Soyut metodlar ──────────────────────────────────────────────────────

    @abstractmethod
    def _build_system_prompt(self) -> str: ...

    @abstractmethod
    async def execute(self, task: Task, emit: Emitter = noop) -> AgentResult: ...

    # ── LLM Üretimi (Streaming destekli) ────────────────────────────────────

    # ── Tekrar tespiti ──────────────────────────────────────────────────────

    @staticmethod
    def _is_repeating(text: str, block: int = 250, repeats: int = 3) -> bool:
        """
        Son `block` karakterin metinde `repeats` veya daha fazla kez geçip
        geçmediğini kontrol eder. Repetition loop tespiti için.
        """
        if len(text) < block * repeats:
            return False
        tail = text[-block:]
        # Tail çok kısa veya sadece boşluksa atla
        if len(tail.strip()) < 20:
            return False
        return text.count(tail) >= repeats

    @staticmethod
    def _dedupe_output(text: str) -> str:
        """
        Tekrar eden satır bloklarını temizler.
        Aynı satır 3'ten fazla art arda tekrarlanıyorsa 1'e indirir.
        """
        lines   = text.splitlines()
        result  : list[str] = []
        counts  : dict[str, int] = {}
        for line in lines:
            key = line.strip()
            if not key:
                result.append(line)
                counts = {}   # boş satırda sayacı sıfırla
                continue
            counts[key] = counts.get(key, 0) + 1
            if counts[key] <= 2:       # aynı satırı en fazla 2 kez tut
                result.append(line)
        return "\n".join(result)

    async def _generate(
        self,
        user_message: str,
        task_id:        str      = "",
        emit:           Emitter  = noop,
        include_history: bool    = False,
        history_n:      int      = 6,
        max_chars:      int      = 12_000,
    ) -> str:
        """
        LLM çağrısı yap. emit fonksiyonu varsa streaming kullan.

        Stream modunda:
          - Her chunk UI'a task.stream eventi olarak gönderilir
          - Repetition loop tespit edilince stream kesilir
          - max_chars aşılırsa stream kesilir

        Blocking modunda (CLI):
          - Tek seferde üretilir, rich console'a yazılır
        """
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        if include_history:
            messages.extend(self.memory.get_as_dicts(last_n=history_n))
        messages.append({"role": "user", "content": user_message})

        t0   = time.perf_counter()
        full = ""
        role = self.agent_type.value

        def _elapsed() -> str:
            return f"{time.perf_counter() - t0:.1f}s"

        if emit is not noop:
            # ── Streaming modu ──────────────────────────────────────────
            _in_think   = False
            _think_buf  = ""
            _truncated  = False
            _token_count = 0
            _first_token = False

            console.print(
                f"    [dim cyan][{role}] LLM başlatılıyor "
                f"({self._model_label}) — "
                f"prompt: {len(user_message):,} karakter[/dim cyan]"
            )

            # İlk token için ayrı bir asyncio event ile timeout uygula
            import asyncio as _asyncio
            import time as _time_mod

            async def _stream_with_first_token_timeout():
                nonlocal full, _in_think, _think_buf, _truncated, _token_count, _first_token

                stream_iter = self.llm.stream(messages).__aiter__()

                # ── İlk token timeout (180 sn) + periyodik log ────────
                # Büyük context'lerde KV prefill 60-120s sürebilir.
                FIRST_TOKEN_TIMEOUT = 180.0

                async def _wait_first_token():
                    """İlk token'ı beklerken her 15s log yazar."""
                    deadline = _time_mod.perf_counter() + FIRST_TOKEN_TIMEOUT
                    _tick = _asyncio.create_task(stream_iter.__anext__())
                    logged = set()
                    while True:
                        remaining = deadline - _time_mod.perf_counter()
                        if remaining <= 0:
                            _tick.cancel()
                            raise _asyncio.TimeoutError
                        wait_s = min(15.0, remaining)
                        done, _ = await _asyncio.wait({_tick}, timeout=wait_s)
                        if done:
                            return _tick.result()   # raises StopAsyncIteration if done
                        elapsed_s = int(time.perf_counter() - t0)
                        if elapsed_s not in logged:
                            logged.add(elapsed_s)
                            console.print(
                                f"    [yellow][{role}] ⏳ İlk token bekleniyor... "
                                f"{elapsed_s}s (KV prefill devam ediyor)[/yellow]"
                            )

                try:
                    first_chunk = await _wait_first_token()
                except _asyncio.TimeoutError:
                    console.print(
                        f"    [bold red][{role}] ⏱ İLK TOKEN GELMEDİ — "
                        f"180 saniye beklendi, LLM yanıt vermedi![/bold red]"
                    )
                    return False   # başarısız
                except StopAsyncIteration:
                    return True    # boş yanıt ama sorun yok

                # İlk token geldi
                _first_token = True
                elapsed_first = time.perf_counter() - t0
                console.print(
                    f"    [green][{role}] ✓ İlk token: {elapsed_first:.1f}s[/green]"
                )
                full += first_chunk
                _token_count += 1
                visible = _filter_think_chunk(first_chunk, _think_buf, _in_think)
                _in_think, _think_buf = visible[1], visible[2]
                if visible[0]:
                    await emit(wrap("task.stream", {
                        "task_id":    task_id,
                        "agent_type": role,
                        "chunk":      visible[0],
                    }))

                # ── Geri kalan stream ──────────────────────────────────
                _last_log = time.perf_counter()
                async for chunk in stream_iter:
                    full += chunk
                    _token_count += 1

                    # 30 sn'de bir ilerleme logu
                    now = time.perf_counter()
                    if now - _last_log >= 30:
                        console.print(
                            f"    [dim][{role}] ⏳ Üretiyor... "
                            f"{_elapsed()} | {len(full):,} karakter[/dim]"
                        )
                        _last_log = now

                    if len(full) > max_chars:
                        full += "\n\n[OUTPUT TRUNCATED — max length reached]"
                        _truncated = True
                        break

                    if len(full) % 50 < len(chunk) and self._is_repeating(full):
                        full = self._dedupe_output(full)
                        full += "\n\n[OUTPUT TRUNCATED — repetition detected]"
                        _truncated = True
                        console.print(
                            f"    [yellow]⚠ [{role}] Tekrar döngüsü tespit edildi![/yellow]"
                        )
                        break

                    visible = _filter_think_chunk(chunk, _think_buf, _in_think)
                    _in_think, _think_buf = visible[1], visible[2]
                    if visible[0]:
                        await emit(wrap("task.stream", {
                            "task_id":    task_id,
                            "agent_type": role,
                            "chunk":      visible[0],
                        }))

                return True

            try:
                success = await _stream_with_first_token_timeout()
                if not success:
                    # İlk token timeout → blocking fallback
                    console.print(f"    [yellow][{role}] Blocking fallback deneniyor...[/yellow]")
                    full = await self.llm.generate(messages)
                    full = _strip_think_blocks(full)
            except Exception as exc:
                console.print(f"    [red][{role}] Stream hatası: {exc}[/red]")
                full = await self.llm.generate(messages)
                full = _strip_think_blocks(full)

            if _truncated:
                # Truncated bildirimini de UI'a gönder
                await emit(wrap("task.stream", {
                    "task_id":    task_id,
                    "agent_type": self.agent_type.value,
                    "chunk":      "\n\n[⚠ Çıktı kesildi]",
                }))
        else:
            # ── Blocking modu (CLI) ─────────────────────────────────────
            console.print(
                f"    [dim]↳ [{self.agent_type.value}] "
                f"{self._model_label} ile üretiyor...[/dim]"
            )
            full = await self.llm.generate(messages)

        elapsed = time.perf_counter() - t0
        console.print(f"    [dim]  ✓ {elapsed:.1f}s[/dim]")

        self.memory.add("user",      user_message)
        self.memory.add("assistant", full)
        return full

    # ── Sonuç oluşturucular ─────────────────────────────────────────────────

    def _ok(self, task: Task, output: str, **meta) -> AgentResult:
        return AgentResult(
            task_id    = task.id,
            agent_type = self.agent_type,
            success    = True,
            output     = output,
            metadata   = meta,
        )

    def _fail(self, task: Task, error: str) -> AgentResult:
        console.print(
            f"    [red]✗ [{self.agent_type.value}] Hata: {error[:120]}[/red]"
        )
        return AgentResult(
            task_id    = task.id,
            agent_type = self.agent_type,
            success    = False,
            output     = "",
            errors     = [error],
        )
