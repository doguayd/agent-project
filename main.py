"""
Multi-Agent Kodlama Sistemi — Giriş Noktası
============================================
Kullanım:
  python main.py              # Etkileşimli CLI modu
  python main.py "görev"      # Tek görev modu (CLI)
  python main.py --web        # Web UI'ı başlat (http://localhost:8000)
  python main.py --check      # Sistem sağlık kontrolü
  python main.py --models     # Model konfigürasyonunu göster
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()

BANNER = """\
[bold blue]
╔══════════════════════════════════════════════════════════╗
║         ⚡  Multi-Agent Kodlama Sistemi  ⚡              ║
║  Supervisor: Auto  │  Yerel: RTX 4090 GPU  │  Ollama   ║
╚══════════════════════════════════════════════════════════╝
[/bold blue]"""

HELP_TEXT = """\
[bold]Komutlar:[/bold]
  [green]<görev>[/green]       → Ajanları çalıştır  [dim](Ctrl+Enter)[/dim]
  [cyan]web[/cyan]            → Web UI'ı başlat  [dim](http://localhost:8000)[/dim]
  [cyan]check[/cyan]          → Sistem sağlık kontrolü
  [cyan]models[/cyan]         → Model konfigürasyonunu göster
  [cyan]memory[/cyan]         → Vektör bellek durumu
  [cyan]history[/cyan]        → Son görev geçmişi
  [cyan]help[/cyan]           → Bu yardım menüsü
  [cyan]exit[/cyan]           → Çıkış
"""


# ─── Supervisor Otomatik Seçimi ──────────────────────────────────────────────

async def init_supervisor() -> tuple[str, str]:
    """
    İnternet + API anahtarı kontrolü yaparak en iyi supervisor modelini seç.
    Sonucu MODELS dict'ine yazar.
    """
    from config import MODELS, SUPERVISOR_PROVIDER
    from core.llm_client import auto_select_supervisor

    if SUPERVISOR_PROVIDER == "auto":
        provider, model = await auto_select_supervisor()
    elif SUPERVISOR_PROVIDER == "gemini":
        provider, model = "gemini", "gemini-2.0-flash"
    elif SUPERVISOR_PROVIDER == "claude":
        provider, model = "claude", "claude-sonnet-4-6"
    else:  # "ollama" veya bilinmeyen
        from core.llm_client import auto_select_supervisor as _aso
        # İnternet olmasa bile çağır — yerel modeli seçer
        provider, model = await _aso()

    MODELS["supervisor"]["provider"] = provider
    MODELS["supervisor"]["model"]    = model
    return provider, model


# ─── Sağlık Kontrolü ────────────────────────────────────────────────────────

async def check_system() -> None:
    from config import MODELS, OLLAMA_HOST, WORKSPACE_DIR
    from core.llm_client import check_internet, get_ollama_models
    from core.vector_memory import VectorMemory

    console.print("\n[bold]🔍 Sistem Sağlık Kontrolü[/bold]\n")

    rows: list[tuple[str, str, str]] = []

    # İnternet
    online = await check_internet()
    rows.append(("İnternet", "✅ Bağlı" if online else "⚠ Çevrimdışı",
                 "Gemini kullanılabilir" if online else "Yalnızca yerel modeller"))

    # Supervisor
    provider, model = await init_supervisor()
    mode = "🌐 Bulut" if provider != "ollama" else "💻 Yerel"
    rows.append(("Supervisor", f"✅ {provider}:{model}", mode))

    # Ollama
    try:
        models = await get_ollama_models()
        rows.append(("Ollama", f"✅ Bağlandı", f"{len(models)} model kurulu"))
    except Exception as e:
        rows.append(("Ollama", "❌ Bağlanamadı", str(e)[:60]))

    # GPU
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu",
            "--format=csv,noheader",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            info = " | ".join(p.strip() for p in out.decode().strip().split(","))
            rows.append(("GPU (CUDA)", "✅ Aktif", info))
        else:
            rows.append(("GPU (CUDA)", "⚠ Devre Dışı", "CPU modu"))
    except Exception:
        rows.append(("GPU (CUDA)", "⚠ Tespit Edilemedi", "CPU modu"))

    # Gemini API
    from config import GOOGLE_API_KEY
    if GOOGLE_API_KEY and GOOGLE_API_KEY != "your_gemini_api_key_here":
        rows.append(("Gemini API", "✅ Anahtar var", "gemini-2.0-flash"))
    else:
        rows.append(("Gemini API", "❌ Anahtar eksik", ".env → GOOGLE_API_KEY"))

    # Vector Bellek
    try:
        vm    = VectorMemory()
        count = await vm.count()
        rows.append(("Vector Bellek", "✅ ChromaDB hazır", f"{count} oturum kayıtlı"))
    except Exception as e:
        rows.append(("Vector Bellek", "⚠ ChromaDB yok", "pip install chromadb"))

    # Workspace
    ws = Path(WORKSPACE_DIR)
    ws.mkdir(exist_ok=True)
    rows.append(("Workspace", "✅ Hazır", str(ws.resolve())))

    tbl = Table(show_header=True, header_style="bold cyan", show_lines=True)
    tbl.add_column("Bileşen",  width=18)
    tbl.add_column("Durum",    width=24)
    tbl.add_column("Detay")
    for name, status, detail in rows:
        tbl.add_row(name, status, detail)

    console.print(tbl)
    console.print()


# ─── Model Tablosu ──────────────────────────────────────────────────────────

def show_models() -> None:
    from config import MODELS
    tbl = Table(title="Model Konfigürasyonu", show_header=True,
                header_style="bold magenta", show_lines=True)
    tbl.add_column("Ajan",      width=14)
    tbl.add_column("Persona",   width=10)
    tbl.add_column("Sağlayıcı",width=10)
    tbl.add_column("Model",     width=30)
    tbl.add_column("Sıcaklık", width=10, justify="right")
    tbl.add_column("Açıklama")

    colors = {
        "supervisor": "blue", "coder": "green", "reviewer": "yellow",
        "tester": "cyan", "researcher": "magenta", "debugger": "red", "fast": "white",
    }
    for role, cfg in MODELS.items():
        c = colors.get(role, "white")
        tbl.add_row(
            f"[{c}]{role}[/{c}]",
            cfg.get("persona", "—"),
            cfg["provider"],
            cfg["model"],
            str(cfg.get("temperature", "—")),
            cfg.get("description", ""),
        )
    console.print(tbl)


# ─── Vector Bellek Durumu ────────────────────────────────────────────────────

async def show_memory() -> None:
    from core.vector_memory import VectorMemory
    vm    = VectorMemory()
    count = await vm.count()
    console.print(
        Panel(
            f"[green]{count}[/green] oturum kayıtlı\n"
            f"[dim]Konum: ./chroma_db[/dim]",
            title="📚 Vector Bellek (ChromaDB)",
            border_style="blue",
        )
    )


# ─── Etkileşimli CLI ────────────────────────────────────────────────────────

async def interactive_loop() -> None:
    from orchestrator import Orchestrator

    # Supervisor'ı önce seç (API key kontrolü → local fallback)
    provider, model = await init_supervisor()

    orch    = Orchestrator()
    history: list[str] = []

    orch.supervisor.refresh_llm()

    console.print(BANNER)
    console.print(
        f"  Supervisor: [bold blue]{provider}:{model}[/bold blue]  "
        f"({'🌐 Çevrimiçi' if provider != 'ollama' else '💻 Çevrimdışı'})"
    )
    console.print()
    console.print(HELP_TEXT)

    while True:
        try:
            goal = Prompt.ask("\n[bold green]Görev[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Görüşmek üzere![/yellow]")
            break

        if not goal:
            continue

        match goal.lower():
            case "exit" | "quit" | "çıkış":
                console.print("[yellow]Görüşmek üzere![/yellow]")
                break
            case "help" | "yardım":
                console.print(HELP_TEXT)
            case "check" | "kontrol":
                await check_system()
            case "models" | "modeller":
                show_models()
            case "memory" | "bellek":
                await show_memory()
            case "web":
                console.print("[blue]Web sunucusu başlatılıyor... http://localhost:8000[/blue]")
                import subprocess
                subprocess.Popen([sys.executable, "server.py"])
                console.print("[green]✓ Tarayıcında http://localhost:8000 adresini aç.[/green]")
            case "history" | "geçmiş":
                if history:
                    for i, h in enumerate(history[-10:], 1):
                        console.print(f"  [dim]{i}.[/dim] {h}")
                else:
                    console.print("[dim]Henüz görev geçmişi yok.[/dim]")
            case _:
                history.append(goal)
                try:
                    await orch.run(goal)
                except Exception as exc:
                    console.print(f"[red]Hata: {exc}[/red]")
                    import traceback
                    console.print(f"[dim]{traceback.format_exc()}[/dim]")


# ─── Tek Görev Modu ─────────────────────────────────────────────────────────

async def single_task(goal: str) -> None:
    from orchestrator import Orchestrator
    await init_supervisor()
    orch = Orchestrator()
    orch.supervisor.refresh_llm()
    await orch.run(goal)


# ─── Web Modu ───────────────────────────────────────────────────────────────

def start_web() -> None:
    import uvicorn
    from config import WS_HOST, WS_PORT
    console.print(f"\n[bold blue]🌐 Web UI[/bold blue] → http://localhost:{WS_PORT}\n")
    uvicorn.run("server:app", host=WS_HOST, port=WS_PORT, log_level="info")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if "--check" in args:
        asyncio.run(check_system())
    elif "--models" in args:
        asyncio.run(init_supervisor())
        show_models()
    elif "--web" in args or "web" in args:
        start_web()
    elif args:
        goal = " ".join(a for a in args if not a.startswith("--"))
        if goal:
            asyncio.run(single_task(goal))
        else:
            asyncio.run(interactive_loop())
    else:
        asyncio.run(interactive_loop())


if __name__ == "__main__":
    main()
