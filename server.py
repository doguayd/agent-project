"""
FastAPI WebSocket Sunucusu
==========================
Endpoints:
  GET  /                  → index.html
  GET  /health            → { ok, supervisor, online, ollama_models }
  GET  /supervisor/models → Mevcut Ollama modelleri listesi
  POST /upload/chat       → Dosya/fotoğraf yükle, içerik çıkar (multimodal)
  WS   /ws                → Gerçek zamanlı ajan event akışı

WS Mesajları (→ gelen, ← giden):
  → run              { goal, context, attachments? }
  → property_search  { query }
  → car_search       { query }
  → finance_analyze  { query }
  → osint_search     { query }
  → music_generate   { query }
  → stop / ping / check / set_supervisor / clarify
  ← ready, plan.created, task.*, supervisor.*, session.complete,
    property.*, car.*, finance.*, osint.*, music.*, file.uploaded ...
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


@app.post("/upload/chat")
async def chat_upload(file: UploadFile = File(...)):
    """
    Chat için dosya/fotoğraf yükle.
    Desteklenen: resim (jpg/png/gif/webp), PDF, metin/kod dosyaları.

    Returns:
      {
        "type": "image" | "text" | "pdf",
        "name": str,
        "content": str,       # text ve pdf için içerik
        "path": str,          # resimler için kaydedilen yol
        "description": str,   # resimler için vision modeli açıklaması
        "size": int,
      }
    """
    import aiofiles, base64, mimetypes

    filename    = file.filename or "upload"
    content     = await file.read()
    size        = len(content)
    mime        = file.content_type or mimetypes.guess_type(filename)[0] or ""
    ext         = Path(filename).suffix.lower()

    # ── Kaydetme yolu ────────────────────────────────────────────────────────
    upload_dir = Path("workspace") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / filename
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    # ── Resim ────────────────────────────────────────────────────────────────
    if mime.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        description = await _describe_image(dest, content)
        return JSONResponse({
            "type":        "image",
            "name":        filename,
            "path":        str(dest),
            "description": description,
            "content":     f"[Resim: {filename}]\n{description}",
            "size":        size,
        })

    # ── PDF ──────────────────────────────────────────────────────────────────
    if mime == "application/pdf" or ext == ".pdf":
        text = await _extract_pdf_text(dest)
        return JSONResponse({
            "type":    "pdf",
            "name":    filename,
            "path":    str(dest),
            "content": f"[PDF: {filename}]\n{text[:8000]}",
            "size":    size,
        })

    # ── Metin / Kod ──────────────────────────────────────────────────────────
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        text = content.decode("latin-1", errors="replace")

    return JSONResponse({
        "type":    "text",
        "name":    filename,
        "path":    str(dest),
        "content": f"[Dosya: {filename}]\n```\n{text[:12000]}\n```",
        "size":    size,
    })


async def _describe_image(path: Path, content: bytes) -> str:
    """Resmi vision modeli ile açıkla."""
    # Önce Gemini dene (online), sonra Ollama gemma4:26b (offline)
    try:
        import base64
        from config import GOOGLE_API_KEY, VISION_MODEL, OLLAMA_HOST
        import mimetypes
        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"

        # Gemini ile dene (online)
        if GOOGLE_API_KEY and GOOGLE_API_KEY != "your_google_api_key_here":
            try:
                from google import genai
                from google.genai import types as gt
                client = genai.Client(api_key=GOOGLE_API_KEY)
                b64    = base64.b64encode(content).decode()
                resp   = await client.aio.models.generate_content(
                    model    = "gemini-2.0-flash",
                    contents = [
                        gt.Content(parts=[
                            gt.Part(inline_data=gt.Blob(mime_type=mime, data=content)),
                            gt.Part(text="Bu resmi Türkçe olarak detaylı açıkla. Ne görüyorsun?"),
                        ], role="user")
                    ],
                )
                return resp.text or "Resim açıklaması alınamadı."
            except Exception:
                pass

        # Ollama gemma4:26b ile dene (offline multimodal)
        try:
            import ollama as _ollama
            b64    = base64.b64encode(content).decode()
            client = _ollama.AsyncClient(host=OLLAMA_HOST)
            resp   = await client.chat(
                model    = VISION_MODEL,
                messages = [{
                    "role":    "user",
                    "content": "Bu resmi Türkçe olarak detaylı açıkla. Ne görüyorsun?",
                    "images":  [b64],
                }],
            )
            return resp.message.content or "Resim açıklaması alınamadı."
        except Exception:
            pass

    except Exception:
        pass

    return f"[Resim yüklendi: {path.name}]"


async def _extract_pdf_text(path: Path) -> str:
    """PDF'ten metin çıkar."""
    try:
        import asyncio
        loop = asyncio.get_event_loop()

        def _read():
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                pages  = []
                for page in reader.pages[:20]:  # İlk 20 sayfa
                    pages.append(page.extract_text() or "")
                return "\n\n".join(pages)
            except ImportError:
                pass

            try:
                import fitz  # PyMuPDF
                doc   = fitz.open(str(path))
                pages = [page.get_text() for page in doc[:20]]
                return "\n\n".join(pages)
            except ImportError:
                pass

            return "[PDF okuma kütüphanesi kurulu değil: pip install pypdf]"

        return await loop.run_in_executor(None, _read)
    except Exception as e:
        return f"[PDF okuma hatası: {e}]"


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
    from agents.car_agent      import CarAgent
    from agents.osint_agent    import OsintAgent
    from agents.finance_agent  import FinanceAgent
    from agents.music_agent    import MusicAgent
    from agents.browser_agent  import BrowserAgent
    orch          = Orchestrator(emit=emit)
    property_agt  = PropertyAgent()
    car_agt       = CarAgent()
    osint_agt     = OsintAgent()
    finance_agt   = FinanceAgent()
    music_agt     = MusicAgent()
    browser_agt   = BrowserAgent()
    orch.supervisor.refresh_llm()
    browser_agt.refresh_llm()

    # Browser onay bekleyicisi
    _browser_approval_future: dict = {"fut": None}

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
                    # Eski format — auto_task'a yönlendir
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

                    async def _auto_run(g: str, c: str):
                        """Görevi otomatik sınıflandır ve doğru ajana yönlendir."""
                        cat = await orch.supervisor.classify_task(g)
                        logger.info(f"Auto-route: '{g[:60]}' → {cat}")
                        await emit({"type": "task.classified", "ts": time.time(),
                                    "data": {"category": cat, "goal": g}})

                        if cat == "property":
                            r = await property_agt.search(g, emit=emit)
                            await emit({"type": "property.results", "ts": time.time(), "data": r})
                        elif cat == "car":
                            r = await car_agt.search(g, emit=emit)
                            await emit({"type": "car.results", "ts": time.time(), "data": r})
                        elif cat == "finance":
                            r = await finance_agt.analyze(g, emit=emit)
                            await emit({"type": "finance.results", "ts": time.time(), "data": r})
                        elif cat == "osint":
                            r = await osint_agt.search(g, emit=emit)
                            await emit({"type": "osint.results", "ts": time.time(), "data": r})
                        elif cat == "music":
                            r = await music_agt.create(g, emit=emit)
                            await emit({"type": "music.results", "ts": time.time(), "data": r})
                        elif cat == "browser":
                            async def _approval(action_desc: str, screenshot_b64: str) -> bool:
                                fut = asyncio.get_event_loop().create_future()
                                _browser_approval_future["fut"] = fut
                                await emit({"type": "browser.approval_needed", "ts": time.time(),
                                            "data": {"action": action_desc, "screenshot": screenshot_b64}})
                                try:
                                    return await asyncio.wait_for(fut, timeout=120)
                                except asyncio.TimeoutError:
                                    return False
                            await browser_agt.run(g, emit=emit, approval_callback=_approval, context=c)
                        else:
                            # code mode
                            result = await orch.run(g, c)
                            _last_session["project"] = orch._project
                            return result

                    active_task = asyncio.create_task(_auto_run(goal, context))

                case "property_search":
                    query = msg.get("query", "").strip()
                    if not query:
                        await websocket.send_json({"type": "error", "data": {"message": "Arama sorgusu boş."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "İşlem devam ediyor. Lütfen bekleyin."}})
                        continue

                    async def _run_property(q):
                        result = await property_agt.search(q, emit=emit)
                        await emit({"type": "property.results", "ts": time.time(), "data": result})

                    active_task = asyncio.create_task(_run_property(query))

                case "car_search":
                    query = msg.get("query", "").strip()
                    if not query:
                        await websocket.send_json({"type": "error", "data": {"message": "Araç sorgusu boş."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "İşlem devam ediyor."}})
                        continue

                    async def _run_car(q):
                        result = await car_agt.search(q, emit=emit)
                        await emit({"type": "car.results", "ts": time.time(), "data": result})

                    active_task = asyncio.create_task(_run_car(query))

                case "finance_analyze":
                    query = msg.get("query", "").strip()
                    if not query:
                        await websocket.send_json({"type": "error", "data": {"message": "Finans sorgusu boş."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "İşlem devam ediyor."}})
                        continue

                    async def _run_finance(q):
                        result = await finance_agt.analyze(q, emit=emit)
                        await emit({"type": "finance.results", "ts": time.time(), "data": result})

                    active_task = asyncio.create_task(_run_finance(query))

                case "osint_search":
                    query = msg.get("query", "").strip()
                    if not query:
                        await websocket.send_json({"type": "error", "data": {"message": "OSINT sorgusu boş."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "İşlem devam ediyor."}})
                        continue

                    async def _run_osint(q):
                        result = await osint_agt.search(q, emit=emit)
                        await emit({"type": "osint.results", "ts": time.time(), "data": result})

                    active_task = asyncio.create_task(_run_osint(query))

                case "music_generate":
                    query = msg.get("query", "").strip()
                    if not query:
                        await websocket.send_json({"type": "error", "data": {"message": "Müzik tanımı boş."}})
                        continue
                    if active_task and not active_task.done():
                        await websocket.send_json({"type": "error", "data": {"message": "İşlem devam ediyor."}})
                        continue

                    async def _run_music(q):
                        result = await music_agt.create(q, emit=emit)
                        await emit({"type": "music.results", "ts": time.time(), "data": result})

                    active_task = asyncio.create_task(_run_music(query))

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
                    # Auto-route follow-up messages too
                    async def _followup_run(g: str, c: str):
                        cat = await orch.supervisor.classify_task(g)
                        await emit({"type": "task.classified", "ts": time.time(),
                                    "data": {"category": cat, "goal": g}})
                        if cat == "browser":
                            async def _approval2(action_desc, ss):
                                fut2 = asyncio.get_event_loop().create_future()
                                _browser_approval_future["fut"] = fut2
                                await emit({"type": "browser.approval_needed", "ts": time.time(),
                                            "data": {"action": action_desc, "screenshot": ss}})
                                try:
                                    return await asyncio.wait_for(fut2, timeout=120)
                                except asyncio.TimeoutError:
                                    return False
                            await browser_agt.run(g, emit=emit, approval_callback=_approval2, context=c)
                        elif cat in ("property", "car", "finance", "osint", "music"):
                            # Route to domain agent
                            _agents = {
                                "property": property_agt.search,
                                "car":      car_agt.search,
                                "finance":  finance_agt.analyze,
                                "osint":    osint_agt.search,
                                "music":    music_agt.create,
                            }
                            fn = _agents[cat]
                            r  = await fn(g, emit=emit)
                            await emit({"type": f"{cat}.results", "ts": time.time(), "data": r})
                        else:
                            result = await orch.run(g, c)
                            _last_session["project"] = orch._project
                            return result
                    active_task = asyncio.create_task(_followup_run(message, combined_ctx))

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

                case "browser_approve":
                    # { "type": "browser_approve", "approved": true/false }
                    fut = _browser_approval_future.get("fut")
                    if fut and not fut.done():
                        fut.set_result(bool(msg.get("approved", False)))
                    _browser_approval_future["fut"] = None

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
