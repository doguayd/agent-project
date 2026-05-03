"""
FastAPI WebSocket Sunucusu
==========================
Endpoints:
  GET  /                → index.html
  GET  /health          → { ok, supervisor, online, ollama_models }
  GET  /supervisor/models → Mevcut Ollama modelleri listesi
  WS   /ws              → Gerçek zamanlı ajan event akışı

WS Mesajları:
  → run           { goal, context }
  → stop          {}
  → set_supervisor { provider, model }   ← YENİ: arayüzden model değiştir
  → ping          {}
  → check         {}
  ← ready, plan.created, task.start/stream/complete,
    supervisor.stream/done, session.complete, supervisor_changed ...
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from config import MODELS, LOCAL_SUPERVISOR_PRIORITY, WS_HOST, WS_PORT
from core.events import make_queue_emitter
from core.llm_client import auto_select_supervisor, check_internet, get_ollama_models

logger = logging.getLogger("agent-server")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ─── Global Durum ────────────────────────────────────────────────────────────

_supervisor_info: dict = {}   # provider, model, online
_last_session:    dict = {}   # goal, context — for mid-session Mila messages


# ─── Yardımcı: Supervisor Değiştir ──────────────────────────────────────────

async def _apply_supervisor(provider: str, model: str) -> dict:
    """MODELS dict'ini güncelle, _supervisor_info'yu döndür."""
    MODELS["supervisor"]["provider"] = provider
    MODELS["supervisor"]["model"]    = model
    online = provider != "ollama"
    _supervisor_info.update({"provider": provider, "model": model, "online": online})
    logger.info(f"Supervisor değişti → {provider}:{model}")
    return dict(_supervisor_info)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    provider, model = await auto_select_supervisor()
    await _apply_supervisor(provider, model)
    mode = "online" if provider != "ollama" else "offline"
    logger.info(f"Web UI  →  http://{WS_HOST if WS_HOST != '0.0.0.0' else 'localhost'}:{WS_PORT}  [{mode}]")
    yield


app = FastAPI(title="Multi-Agent Coding System", lifespan=lifespan)
_STATIC = Path(__file__).parent / "static"


# ─── HTTP Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health():
    online       = await check_internet()
    ollama_mods  = await get_ollama_models()
    # ChromaDB bellek sayısı
    memory_count = 0
    try:
        from core.vector_memory import VectorMemory
        memory_count = await VectorMemory().count()
    except Exception:
        pass
    return JSONResponse({
        "ok":             True,
        "supervisor":     _supervisor_info,
        "internet":       online,
        "ollama_models":  ollama_mods,
        "priority_list":  LOCAL_SUPERVISOR_PRIORITY,
        "memory_count":   memory_count,
    })


@app.get("/workspace/files")
async def workspace_files(project: str = ""):
    """Workspace içindeki dosyaları listele."""
    from tools.file_tools import list_workspace_files
    files = await list_workspace_files(project)
    return JSONResponse({"files": files, "project": project})


@app.get("/workspace/read")
async def workspace_read(path: str):
    """Workspace'ten dosya içeriğini oku."""
    from tools.file_tools import read_file
    try:
        content = await read_file(path, workspace=True)
        return JSONResponse({"path": path, "content": content})
    except FileNotFoundError:
        return JSONResponse({"error": "Dosya bulunamadı"}, status_code=404)


@app.post("/workspace/upload")
async def workspace_upload(file: UploadFile = File(...), project: str = "uploads"):
    """Kullanıcıdan dosya al ve workspace'e kaydet."""
    from config import WORKSPACE_DIR
    import aiofiles
    dest = Path(WORKSPACE_DIR) / project / (file.filename or "upload")
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)
    return JSONResponse({
        "saved": str(dest.relative_to(WORKSPACE_DIR)),
        "size":  len(content),
        "name":  file.filename,
    })


@app.get("/settings/agents")
async def get_agent_settings():
    """Mevcut ajan model ayarlarını döndür."""
    worker_agents = ["researcher", "coder", "reviewer", "tester", "debugger"]
    result = {}
    for agent in worker_agents:
        cfg = MODELS.get(agent, MODELS["fast"])
        result[agent] = {
            "provider":    cfg.get("provider", "ollama"),
            "model":       cfg.get("model", ""),
            "temperature": cfg.get("temperature", 0.1),
        }
    return JSONResponse(result)


@app.get("/supervisor/models")
async def supervisor_models():
    """Mevcut Ollama modelleri + bulut seçenekleri — UI dropdown için."""
    online      = await check_internet()
    ollama_mods = await get_ollama_models()

    from config import GOOGLE_API_KEY, ANTHROPIC_API_KEY
    cloud = []
    if online and GOOGLE_API_KEY and GOOGLE_API_KEY != "your_gemini_api_key_here":
        cloud.append({"provider": "gemini", "model": "gemini-2.5-flash-preview-04-17", "label": "Gemini 2.5 Flash ✨", "icon": "🌐"})
        cloud.append({"provider": "gemini", "model": "gemini-2.5-pro-preview-03-25",   "label": "Gemini 2.5 Pro ✨",   "icon": "🌐"})
        cloud.append({"provider": "gemini", "model": "gemini-2.0-flash",   "label": "Gemini 2.0 Flash",   "icon": "🌐"})
    if online and ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_anthropic_api_key_here":
        cloud.append({"provider": "claude", "model": "claude-sonnet-4-6",  "label": "Claude Sonnet",      "icon": "🌐"})

    # Tier labels for installed models
    tier1 = {"nemotron-cascade-2:30b", "qwen3:14b", "gemma4:26b"}
    tier2 = {"mistral-small3:24b", "magistral-small:24b", "phi4-reasoning:14b",
             "phi4:14b", "gpt-oss:20b", "gemma3:27b"}

    local = []
    for m in ollama_mods:
        if m in tier1:
            icon, label = "⭐", f"{m}  ★★★"
        elif m in tier2:
            icon, label = "💫", f"{m}  ★★"
        else:
            icon, label = "💻", m
        local.append({"provider": "ollama", "model": m, "label": label,
                      "icon": icon, "installed": True})

    return JSONResponse({"cloud": cloud, "local": local, "current": _supervisor_info})


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket bağlandı.")

    queue = asyncio.Queue()
    emit  = make_queue_emitter(queue)
    active_task: asyncio.Task | None = None

    from orchestrator import Orchestrator
    from agents.property_agent import PropertyAgent
    orch          = Orchestrator(emit=emit)
    property_agt  = PropertyAgent()
    orch.supervisor.refresh_llm()

    # İlk mesaj
    await websocket.send_json({
        "type": "ready",
        "ts":   time.time(),
        "data": {
            "supervisor_provider": _supervisor_info.get("provider", "?"),
            "supervisor_model":    _supervisor_info.get("model", "?"),
            "online":              _supervisor_info.get("online", False),
        },
    })

    async def drain():
        while True:
            event = await queue.get()
            try:
                await websocket.send_json(event)
            except Exception:
                break

    drain_task = asyncio.create_task(drain())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            match msg.get("type"):

                case "run":
                    goal    = msg.get("goal", "").strip()
                    context = msg.get("context", "").strip()
                    if not goal:
                        await websocket.send_json({"type": "error", "data": {"message": "Görev boş olamaz."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "Görev çalışıyor. Önce durdur."}})
                        continue
                    _last_session["goal"]    = goal
                    _last_session["context"] = context
                    # project slug will be set by orchestrator — capture it after run
                    async def _run_and_save_project(g, c):
                        result = await orch.run(g, c)
                        _last_session["project"] = orch._project
                        return result
                    active_task = asyncio.create_task(_run_and_save_project(goal, context))

                case "property_search":
                    # { "type": "property_search", "query": "Kadıköy 2+1 kiralik 5000-8000" }
                    query = msg.get("query", "").strip()
                    if not query:
                        await websocket.send_json({"type": "error", "data": {"message": "Arama sorgusu boş."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "İşlem devam ediyor. Lütfen bekleyin."}})
                        continue

                    async def _run_property(q):
                        result = await property_agt.search(q, emit=emit)
                        # property.done already emitted by agent — send result data separately
                        await emit({
                            "type": "property.results",
                            "ts":   time.time(),
                            "data": result,
                        })

                    active_task = asyncio.create_task(_run_property(query))

                case "message_mila":
                    # User sends a follow-up message to Mila at any time
                    message = msg.get("message", "").strip()
                    if not message:
                        await websocket.send_json({"type": "error", "data": {"message": "Mesaj boş olamaz."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "Görev çalışıyor. Önce durdur."}})
                        continue
                    # Build context from last session — include saved workspace files
                    prev_goal    = _last_session.get("goal", "")
                    prev_context = _last_session.get("context", "")
                    prev_project = _last_session.get("project", "")
                    combined_ctx = ""
                    if prev_goal:
                        combined_ctx = f"[Previous goal: {prev_goal}]"
                    if prev_context:
                        combined_ctx += f"\n[Previous context: {prev_context[:600]}]"
                    # Include workspace file list so agents know what was created
                    if prev_project:
                        try:
                            from tools.file_tools import list_workspace_files
                            files = await list_workspace_files(prev_project)
                            if files:
                                file_list = "\n".join(f"  • {f}" for f in files[:20])
                                combined_ctx += (
                                    f"\n\n[WORKSPACE FILES from '{prev_project}']\n"
                                    f"{file_list}\n"
                                    f"These files already exist — build on them, do not recreate from scratch."
                                )
                        except Exception:
                            pass
                    # Update last session with new goal
                    _last_session["goal"]    = message
                    _last_session["context"] = combined_ctx
                    await websocket.send_json({
                        "type": "mila.message_received",
                        "ts":   time.time(),
                        "data": {"message": message},
                    })
                    active_task = asyncio.create_task(orch.run(message, combined_ctx))

                case "stop":
                    if active_task and not active_task.done():
                        active_task.cancel()
                        await websocket.send_json({"type": "stopped", "data": {}})

                case "set_supervisor":
                    # { "type": "set_supervisor", "provider": "gemini"|"ollama", "model": "..." }
                    if active_task and not active_task.done():
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "Görev çalışırken supervisor değiştirilemez."}
                        })
                        continue
                    prov  = msg.get("provider", "ollama").strip()
                    model = msg.get("model", "").strip()
                    if not model:
                        await websocket.send_json({"type": "error", "data": {"message": "Model adı boş."}})
                        continue
                    info = await _apply_supervisor(prov, model)
                    orch.supervisor.refresh_llm()
                    await websocket.send_json({
                        "type": "supervisor_changed",
                        "ts":   time.time(),
                        "data": info,
                    })

                case "set_agent_config":
                    # { "type": "set_agent_config", "agent": "coder", "provider": "ollama",
                    #   "model": "...", "temperature": 0.1 }
                    if active_task and not active_task.done():
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "Görev çalışırken ajan ayarı değiştirilemez."}
                        })
                        continue
                    agent_name = msg.get("agent", "").strip()
                    prov       = msg.get("provider", "ollama").strip()
                    model      = msg.get("model", "").strip()
                    temp       = float(msg.get("temperature", 0.1))
                    valid      = ["researcher","coder","reviewer","tester","debugger"]
                    if agent_name not in valid:
                        await websocket.send_json({"type":"error","data":{"message":f"Geçersiz ajan: {agent_name}"}})
                        continue
                    if not model:
                        await websocket.send_json({"type":"error","data":{"message":"Model adı boş."}})
                        continue
                    MODELS[agent_name]["provider"]    = prov
                    MODELS[agent_name]["model"]       = model
                    MODELS[agent_name]["temperature"] = temp
                    logger.info(f"Ajan ayarı değişti → {agent_name}: {prov}:{model} temp={temp}")
                    await websocket.send_json({
                        "type": "agent_config_changed",
                        "ts":   time.time(),
                        "data": {"agent": agent_name, "provider": prov, "model": model, "temperature": temp},
                    })

                case "clarify":
                    # { "type": "clarify", "answers": ["cevap1", "cevap2", ...] }
                    answers = msg.get("answers", [])
                    fut = orch._clarification_future
                    if fut and not fut.done():
                        fut.set_result(answers)
                        await websocket.send_json({
                            "type": "clarification_received",
                            "ts":   time.time(),
                            "data": {"count": len(answers)},
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "Bekleyen bir clarification yok."},
                        })

                case "ping":
                    await websocket.send_json({"type": "pong", "data": {}})

                case "check":
                    online = await check_internet()
                    await websocket.send_json({
                        "type": "status",
                        "data": {"internet": online, "supervisor": _supervisor_info},
                    })

    except WebSocketDisconnect:
        logger.info("WebSocket bağlantısı kesildi.")
    except Exception as exc:
        logger.error(f"WebSocket hatası: {exc}")
    finally:
        drain_task.cancel()
        if active_task and not active_task.done():
            active_task.cancel()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = WS_HOST if WS_HOST != "0.0.0.0" else "localhost"
    print(f"\n  http://{host}:{WS_PORT}\n")
    uvicorn.run(
        "server:app",
        host      = WS_HOST,
        port      = WS_PORT,
        reload    = "--reload" in sys.argv,
        log_level = "info",
    )
