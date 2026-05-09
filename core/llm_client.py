"""
LLM İstemci Soyutlaması
========================
Üç sağlayıcı → tek arayüz:
  - Ollama  → Yerel GPU/CPU (RTX 4090 CUDA otomatik)
  - Gemini  → Google Gemini 2.0 Flash (bulut)
  - Claude  → Anthropic Claude (bulut, isteğe bağlı)

İnternet kontrolü ve otomatik supervisor seçimi burada.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import ollama as _ollama

from config import (
    ANTHROPIC_API_KEY,
    GOOGLE_API_KEY,
    LOCAL_SUPERVISOR_PRIORITY,
    OLLAMA_HOST,
)


# ─── İnternet / API Kontrolleri ─────────────────────────────────────────────

async def check_internet(timeout: float = 3.0) -> bool:
    """Google DNS'e TCP bağlantısı dene → internet var mı?"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("8.8.8.8", 53),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def get_ollama_models() -> list[str]:
    """Ollama'daki kurulu model listesini döndür."""
    try:
        client = _ollama.AsyncClient(host=OLLAMA_HOST)
        resp   = await client.list()
        return [m.model for m in resp.models]
    except Exception:
        return []


async def auto_select_supervisor() -> tuple[str, str]:
    """
    Supervisor için en iyi (provider, model) çiftini belirle.

    Öncelik sırası:
      1. İnternet varsa + GOOGLE_API_KEY → Gemini 2.0 Flash
      2. İnternet varsa + ANTHROPIC_API_KEY → Claude Sonnet
      3. LOCAL_SUPERVISOR_PRIORITY sırasındaki ilk mevcut yerel model
      4. llama3.1:8b (mutlak yedek)
    """
    internet = await check_internet()

    if internet and GOOGLE_API_KEY and GOOGLE_API_KEY != "your_gemini_api_key_here":
        return "gemini", "gemini-2.5-flash-preview-04-17"

    if internet and ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_anthropic_api_key_here":
        return "claude", "claude-sonnet-4-6"

    # Yerel model seç
    available = set(await get_ollama_models())
    for model in LOCAL_SUPERVISOR_PRIORITY:
        if model in available:
            return "ollama", model

    # Mutlak yedek
    return "ollama", "llama3.1:8b"


# ─── Temel Sınıf ────────────────────────────────────────────────────────────

class BaseLLM(ABC):
    @abstractmethod
    async def generate(self, messages: list[dict]) -> str: ...

    @abstractmethod
    def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]: ...


# ─── Ollama (Yerel GPU/CPU) ─────────────────────────────────────────────────

class OllamaLLM(BaseLLM):
    def __init__(self, model: str, temperature: float = 0.1) -> None:
        self.model       = model
        self.temperature = temperature
        self._client     = _ollama.AsyncClient(host=OLLAMA_HOST)

    async def generate(self, messages: list[dict]) -> str:
        resp = await self._client.chat(
            model   = self.model,
            messages= messages,
            options = {"temperature": self.temperature},
            stream  = False,
        )
        return resp.message.content

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        async for chunk in await self._client.chat(
            model   = self.model,
            messages= messages,
            options = {"temperature": self.temperature},
            stream  = True,
        ):
            if chunk.message.content:
                yield chunk.message.content


# ─── Google Gemini (Bulut) ──────────────────────────────────────────────────

class GeminiLLM(BaseLLM):
    def __init__(self, model: str = "gemini-2.0-flash", temperature: float = 0.3) -> None:
        from google import genai
        from google.genai import types as _gt

        self.model       = model
        self.temperature = temperature
        self._gt         = _gt
        self._client     = genai.Client(api_key=GOOGLE_API_KEY)

    def _convert(self, messages: list[dict]) -> tuple[str, list]:
        system  = ""
        history = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            elif m["role"] == "user":
                history.append(self._gt.Content(role="user",  parts=[self._gt.Part(text=m["content"])]))
            elif m["role"] == "assistant":
                history.append(self._gt.Content(role="model", parts=[self._gt.Part(text=m["content"])]))
        return system, history

    def _cfg(self, system: str):
        return self._gt.GenerateContentConfig(
            temperature       = self.temperature,
            system_instruction= system or None,
        )

    async def generate(self, messages: list[dict]) -> str:
        system, history = self._convert(messages)
        resp = await self._client.aio.models.generate_content(
            model   = self.model,
            contents= history,
            config  = self._cfg(system),
        )
        return resp.text

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        system, history = self._convert(messages)
        async for chunk in await self._client.aio.models.generate_content_stream(
            model   = self.model,
            contents= history,
            config  = self._cfg(system),
        ):
            if chunk.text:
                yield chunk.text


# ─── Anthropic Claude (Bulut) ───────────────────────────────────────────────

class ClaudeLLM(BaseLLM):
    def __init__(self, model: str = "claude-sonnet-4-6", temperature: float = 0.3) -> None:
        import anthropic as _anthropic

        self.model       = model
        self.temperature = temperature
        self._client     = _anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    def _split(self, messages: list[dict]) -> tuple[str, list[dict]]:
        system = ""
        rest   = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                rest.append({"role": m["role"], "content": m["content"]})
        return system, rest

    async def generate(self, messages: list[dict]) -> str:
        system, msgs = self._split(messages)
        resp = await self._client.messages.create(
            model      = self.model,
            max_tokens = 8192,
            system     = system or "You are a helpful assistant.",
            messages   = msgs,
            temperature= self.temperature,
        )
        return resp.content[0].text

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        system, msgs = self._split(messages)
        async with self._client.messages.stream(
            model      = self.model,
            max_tokens = 8192,
            system     = system or "You are a helpful assistant.",
            messages   = msgs,
            temperature= self.temperature,
        ) as s:
            async for text in s.text_stream:
                yield text


# ─── Fabrika ────────────────────────────────────────────────────────────────

def create_llm(provider: str, model: str, temperature: float = 0.1) -> BaseLLM:
    match provider:
        case "ollama":  return OllamaLLM(model, temperature)
        case "gemini":  return GeminiLLM(model, temperature)
        case "claude":  return ClaudeLLM(model, temperature)
        case _:
            raise ValueError(f"Bilinmeyen sağlayıcı: {provider!r}")


# ─── MCP Araç Döngüsü ────────────────────────────────────────────────────────

async def run_with_mcp_tools(
    llm:      BaseLLM,
    messages: list[dict],
    provider: str,
    max_rounds: int = 10,
    emit=None,
) -> str:
    """
    LLM'i MCP araçlarıyla çalıştır.
    LLM bir araç çağrısı yapana kadar döngü devam eder.

    Akış:
      1. LLM'e mevcut araçları bildir
      2. LLM yanıt üretir (text veya tool_call)
      3. tool_call varsa → MCPManager üzerinden araç çağrılır
      4. Araç sonucu mesaj geçmişine eklenir
      5. LLM tekrar yanıt üretir (döngü)
      6. Düz text yanıt gelene veya max_rounds dolana kadar devam et

    Not: Şu an Gemini ve Anthropic function calling destekler.
    Ollama tool-use destekli modeller için de çalışır (qwen3, llama3.3).
    """
    from core.mcp_manager import MCPManager
    import json as _json
    import logging as _log
    _logger = _log.getLogger("llm-mcp")

    mcp = MCPManager.instance()
    tools = mcp.get_tools_for_llm(provider)
    msgs = list(messages)

    for round_i in range(max_rounds):
        # ── Gemini function calling ──────────────────────────────────────
        if provider == "gemini" and tools:
            try:
                from google.genai import types as _gt
                gt = llm._gt
                system, history = llm._convert(msgs)
                fd_list = [
                    gt.FunctionDeclaration(**t)
                    for t in tools
                ]
                cfg = gt.GenerateContentConfig(
                    temperature        = llm.temperature,
                    system_instruction = system or None,
                    tools              = [gt.Tool(function_declarations=fd_list)],
                )
                resp = await llm._client.aio.models.generate_content(
                    model    = llm.model,
                    contents = history,
                    config   = cfg,
                )
                # Tool call var mı?
                calls = []
                for part in (resp.candidates[0].content.parts if resp.candidates else []):
                    if hasattr(part, "function_call") and part.function_call:
                        calls.append(part.function_call)

                if not calls:
                    return resp.text or ""

                # Tool call'ları işle
                tool_results = []
                for fc in calls:
                    name = fc.name
                    args = dict(fc.args)
                    _logger.info(f"[MCP] Araç: {name}({args})")
                    if emit:
                        await emit({"type": "mcp.tool_call", "data": {"tool": name, "args": args}})
                    result = await mcp.call_tool(name, args)
                    tool_results.append(gt.Part(
                        function_response=gt.FunctionResponse(
                            name=name, response={"result": result}
                        )
                    ))

                # Geçmişe ekle
                history.append(gt.Content(role="model", parts=[
                    gt.Part(function_call=fc) for fc in calls
                ]))
                history.append(gt.Content(role="user", parts=tool_results))

                # Yeni mesajlar için msgs'i güncelle
                msgs = [m for m in msgs if m.get("role") != "system"]
                if system:
                    msgs = [{"role": "system", "content": system}] + msgs
                continue

            except Exception as e:
                _logger.error(f"Gemini MCP döngüsü hatası: {e}")
                break

        # ── Anthropic function calling ───────────────────────────────────
        elif provider == "anthropic" and tools:
            try:
                import anthropic as _ant
                system, rest = llm._split(msgs)
                resp = await llm._client.messages.create(
                    model      = llm.model,
                    max_tokens = 8192,
                    system     = system or "You are a helpful assistant.",
                    messages   = rest,
                    tools      = tools,
                    temperature= llm.temperature,
                )
                if resp.stop_reason != "tool_use":
                    return "".join(b.text for b in resp.content if hasattr(b, "text"))

                # Tool call
                rest.append({"role": "assistant", "content": resp.content})
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        _logger.info(f"[MCP] Araç: {block.name}({block.input})")
                        if emit:
                            await emit({"type": "mcp.tool_call", "data": {"tool": block.name, "args": block.input}})
                        result = await mcp.call_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                rest.append({"role": "user", "content": tool_results})
                msgs = ([{"role": "system", "content": system}] if system else []) + rest
                continue

            except Exception as e:
                _logger.error(f"Anthropic MCP döngüsü hatası: {e}")
                break

        # ── Ollama tool use ──────────────────────────────────────────────
        elif provider == "ollama" and tools:
            try:
                resp = await llm._client.chat(
                    model    = llm.model,
                    messages = msgs,
                    tools    = tools,
                    options  = {"temperature": llm.temperature},
                    stream   = False,
                )
                msg = resp.message
                if not msg.tool_calls:
                    return msg.content or ""

                msgs.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})
                for tc in msg.tool_calls:
                    fn   = tc.function
                    name = fn.name
                    args = dict(fn.arguments) if fn.arguments else {}
                    _logger.info(f"[MCP] Araç: {name}({args})")
                    if emit:
                        await emit({"type": "mcp.tool_call", "data": {"tool": name, "args": args}})
                    result = await mcp.call_tool(name, args)
                    msgs.append({"role": "tool", "content": result})
                continue

            except Exception as e:
                _logger.error(f"Ollama MCP döngüsü hatası: {e}")
                break

        # Araç yok veya provider desteklemiyor → normal generate
        break

    # Fallback: normal generate
    return await llm.generate(msgs)
