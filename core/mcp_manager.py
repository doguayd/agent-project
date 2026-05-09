"""
MCP Manager — Atlas
====================
mcp.json'dan sunucu konfigürasyonunu okur, her sunucuyu arka planda spawn eder
ve LLM'e function-calling için araç listesi sunar.

Mimari:
    mcp.json
        ↓ (startup)
    MCPManager.start()
        ↓ (per server)
    asyncio subprocess (stdio transport)
        ↓ (JSON-RPC 2.0)
    MCP Server (tools/main.py, node scripts, vb.)

LLM Entegrasyonu:
    mcm = MCPManager.instance()
    tools  = mcm.get_tools_schema()   # OpenAI / Gemini / Anthropic tool format
    result = await mcm.call_tool("tool_name", {"arg": "val"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("mcp-manager")

# ─── Veri Tipleri ─────────────────────────────────────────────────────────────

class MCPTool:
    """Bir MCP sunucusundan keşfedilen araç."""
    __slots__ = ("name", "description", "input_schema", "server_name")

    def __init__(self, name: str, description: str, input_schema: dict, server_name: str):
        self.name         = name
        self.description  = description
        self.input_schema = input_schema
        self.server_name  = server_name

    def to_gemini(self) -> dict:
        """Gemini function declaration formatı."""
        params = self.input_schema.get("properties", {})
        required = self.input_schema.get("required", [])
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    k: {
                        "type": v.get("type", "STRING").upper(),
                        "description": v.get("description", ""),
                    }
                    for k, v in params.items()
                },
                "required": required,
            }
        }

    def to_anthropic(self) -> dict:
        """Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_openai(self) -> dict:
        """OpenAI / Ollama function format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            }
        }


# ─── MCP Stdio Transport ──────────────────────────────────────────────────────

class MCPSession:
    """
    Tek bir MCP sunucusuyla stdio üzerinden JSON-RPC 2.0 iletişimi.
    MCP SDK'yı kullanmak yerine saf asyncio subprocess ile yapıyoruz —
    böylece server tarafı SDK bağımsızlığı sağlanır.
    """

    def __init__(self, name: str, config: dict):
        self.name    = name
        self.config  = config
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._lock   = asyncio.Lock()
        self.tools: list[MCPTool] = []
        self.ready   = False

    async def start(self, project_root: Path) -> bool:
        """Sunucu sürecini başlat, initialize et, araç listesini al."""
        cmd  = self.config["command"]
        args = self.config.get("args", [])
        cwd  = self.config.get("cwd", ".")
        env  = {**os.environ, **self.config.get("env", {})}

        work_dir = (project_root / cwd).resolve()

        try:
            self._proc = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdin  = asyncio.subprocess.PIPE,
                stdout = asyncio.subprocess.PIPE,
                stderr = asyncio.subprocess.PIPE,
                cwd    = str(work_dir),
                env    = env,
            )
            logger.info(f"[MCP:{self.name}] PID {self._proc.pid} başladı — {cmd} {' '.join(args)}")

            # Kısa süre bekle, process hemen çıktıysa stderr'i logla
            await asyncio.sleep(0.5)
            if self._proc.returncode is not None:
                err_bytes = await self._proc.stderr.read()
                err_text  = err_bytes.decode(errors="replace").strip()
                logger.error(f"[MCP:{self.name}] Process anında çıktı (code={self._proc.returncode})")
                if err_text:
                    logger.error(f"[MCP:{self.name}] Stderr:\n{err_text[:500]}")
                return False

            # initialize
            resp = await self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities":    {"tools": {}},
                "clientInfo":      {"name": "Atlas", "version": "1.0"},
            })
            if "error" in resp:
                logger.error(f"[MCP:{self.name}] initialize hatası: {resp['error']}")
                return False

            # initialized notification
            await self._notify("notifications/initialized")

            # Araç listesi
            await self._refresh_tools()

            self.ready = True
            logger.info(f"[MCP:{self.name}] Hazır — {len(self.tools)} araç")
            return True

        except FileNotFoundError:
            logger.error(f"[MCP:{self.name}] Komut bulunamadı: {cmd}")
            return False
        except Exception as e:
            logger.error(f"[MCP:{self.name}] Başlatma hatası: {e}")
            return False

    async def _refresh_tools(self):
        """Araç listesini sunucudan çek."""
        resp = await self._rpc("tools/list", {})
        raw_tools = resp.get("result", {}).get("tools", [])
        self.tools = [
            MCPTool(
                name        = t["name"],
                description = t.get("description", ""),
                input_schema= t.get("inputSchema", {}),
                server_name = self.name,
            )
            for t in raw_tools
        ]

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Araç çağır, metin sonuç döndür."""
        resp = await self._rpc("tools/call", {
            "name":      tool_name,
            "arguments": arguments,
        })

        if "error" in resp:
            return f"Hata: {resp['error'].get('message', resp['error'])}"

        content = resp.get("result", {}).get("content", [])
        parts = []
        for item in content:
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "image":
                parts.append(f"[Görsel: {item.get('mimeType','image')}]")
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else "(boş yanıt)"

    # ── JSON-RPC primitives ────────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        """JSON-RPC request gönder, yanıt bekle."""
        async with self._lock:
            self._req_id += 1
            req_id = self._req_id
            msg = json.dumps({
                "jsonrpc": "2.0",
                "id":      req_id,
                "method":  method,
                "params":  params,
            }) + "\n"

            try:
                self._proc.stdin.write(msg.encode())
                await self._proc.stdin.drain()

                # Yanıtı oku (satır satır, id eşleşene kadar)
                deadline = asyncio.get_event_loop().time() + timeout
                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        return {"error": {"message": "Zaman aşımı"}}
                    line = await asyncio.wait_for(
                        self._proc.stdout.readline(), timeout=remaining
                    )
                    if not line:
                        return {"error": {"message": "Sunucu kapandı"}}
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("id") == req_id:
                        return data
                    # Başka id veya notification → devam et

            except asyncio.TimeoutError:
                return {"error": {"message": "Zaman aşımı"}}
            except Exception as e:
                return {"error": {"message": str(e)}}

    async def _notify(self, method: str, params: dict = {}):
        """JSON-RPC notification gönder (yanıt bekleme)."""
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        try:
            self._proc.stdin.write(msg.encode())
            await self._proc.stdin.drain()
        except Exception:
            pass

    async def stop(self):
        """Süreci kapat."""
        if self._proc:
            try:
                self._proc.stdin.close()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                self._proc.kill()
            self._proc = None
        self.ready = False


# ─── Manager ──────────────────────────────────────────────────────────────────

class MCPManager:
    """
    mcp.json'dan sunucuları okur, başlatır, araç çağrılarını yönlendirir.
    Singleton pattern — her yerde MCPManager.instance() ile erişilir.
    """
    _instance: MCPManager | None = None

    def __init__(self, config_path: Path | None = None, project_root: Path | None = None):
        self._config_path   = config_path or Path("mcp.json")
        self._project_root  = project_root or Path(".").resolve()
        self._sessions:  dict[str, MCPSession] = {}
        self._tool_index: dict[str, MCPSession] = {}   # tool_name → session
        self._started = False

    @classmethod
    def instance(cls) -> MCPManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Yaşam Döngüsü ─────────────────────────────────────────────────────

    async def start(self):
        """Tüm etkin MCP sunucularını başlat."""
        if self._started:
            return
        self._started = True

        if not self._config_path.exists():
            logger.info("[MCPManager] mcp.json bulunamadı — MCP sunucuları devre dışı")
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"[MCPManager] mcp.json okuma hatası: {e}")
            return

        servers = config.get("mcpServers", {})
        tasks = []
        for name, srv_cfg in servers.items():
            if not srv_cfg.get("enabled", True):
                logger.info(f"[MCPManager] {name} devre dışı, atlanıyor")
                continue
            session = MCPSession(name, srv_cfg)
            self._sessions[name] = session
            tasks.append(self._start_session(session))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        total = sum(1 for s in self._sessions.values() if s.ready)
        tool_count = len(self._tool_index)
        logger.info(f"[MCPManager] {total}/{len(self._sessions)} sunucu aktif, {tool_count} araç")

    async def _start_session(self, session: MCPSession):
        ok = await session.start(self._project_root)
        if ok:
            for tool in session.tools:
                self._tool_index[tool.name] = session
            logger.info(
                f"[MCPManager] '{session.name}' — "
                f"{[t.name for t in session.tools[:5]]}{'...' if len(session.tools)>5 else ''}"
            )
        else:
            logger.warning(f"[MCPManager] '{session.name}' başlatılamadı")

    async def stop(self):
        """Tüm sunucuları kapat."""
        await asyncio.gather(
            *(s.stop() for s in self._sessions.values()),
            return_exceptions=True,
        )
        self._sessions.clear()
        self._tool_index.clear()
        self._started = False

    async def restart_server(self, name: str) -> bool:
        """Belirli bir sunucuyu yeniden başlat (hot-reload)."""
        session = self._sessions.get(name)
        if not session:
            return False
        # Araç indexinden kaldır
        for tool_name in list(self._tool_index):
            if self._tool_index[tool_name].name == name:
                del self._tool_index[tool_name]
        await session.stop()
        ok = await session.start(self._project_root)
        if ok:
            for tool in session.tools:
                self._tool_index[tool.name] = session
        return ok

    # ── Araç Erişimi ───────────────────────────────────────────────────────

    def get_all_tools(self) -> list[MCPTool]:
        """Tüm aktif sunuculardan tüm araçları listele."""
        tools = []
        for session in self._sessions.values():
            if session.ready:
                tools.extend(session.tools)
        return tools

    def get_tools_for_llm(self, provider: str) -> list[dict]:
        """
        LLM'in beklediği formatta araç listesi.
        provider: "gemini" | "anthropic" | "ollama" | "openai"
        """
        tools = self.get_all_tools()
        if not tools:
            return []
        if provider == "anthropic":
            return [t.to_anthropic() for t in tools]
        elif provider == "gemini":
            return [t.to_gemini() for t in tools]
        else:  # ollama, openai
            return [t.to_openai() for t in tools]

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Araç adına göre doğru sunucuya yönlendir ve çağır."""
        session = self._tool_index.get(tool_name)
        if not session:
            return f"Araç bulunamadı: {tool_name}"
        if not session.ready:
            return f"Sunucu hazır değil: {session.name}"
        return await session.call_tool(tool_name, arguments)

    def status(self) -> dict:
        """Sunucu ve araç durumu."""
        return {
            "servers": {
                name: {
                    "ready":  s.ready,
                    "tools":  len(s.tools),
                    "tool_names": [t.name for t in s.tools],
                }
                for name, s in self._sessions.items()
            },
            "total_tools": len(self._tool_index),
        }
