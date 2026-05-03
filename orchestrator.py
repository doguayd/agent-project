"""
Orkestratör
===========
Supervisor'ın planını alır, ajanları koordine eder:
  • Aynı parallel_group'taki bağımsız görevler → eş zamanlı
  • Bağımlı görevlere bağlam enjeksiyonu
  • emit callback aracılığıyla UI'ya gerçek zamanlı eventler
  • Vector Memory: geçmiş bağlam çekme + oturum kaydetme
  • GPU yoksa otomatik CPU fallback (Ollama sayesinde)
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents import (
    CoderAgent, DebuggerAgent, ResearcherAgent, ReviewerAgent,
    SupervisorAgent, TesterAgent,
)
from agents.base_agent import BaseAgent
from config import MAX_CTX_CHARS, MAX_PARALLEL, CHROMA_PATH, OLLAMA_HOST, MODELS
from core.llm_client import create_llm, get_ollama_models
from core.events import Emitter, noop, wrap
from core.memory import ConversationMemory
from core.models import (
    AgentResult, AgentType, ExecutionPlan, SystemState, Task, TaskStatus,
)
from core.vector_memory import VectorMemory
from core.watchdog import Watchdog, WatchdogCancelled
from tools.file_tools import save_code_files

console = Console()


class Orchestrator:
    """Tam oturum yöneticisi."""

    def __init__(self, emit: Emitter = noop) -> None:
        self._emit       = emit
        shared_mem       = ConversationMemory(agent_name="global")
        self.supervisor  = SupervisorAgent(memory=shared_mem)
        self._agents: dict[str, BaseAgent] = {
            AgentType.CODER.value:      CoderAgent(),
            AgentType.REVIEWER.value:   ReviewerAgent(),
            AgentType.TESTER.value:     TesterAgent(),
            AgentType.RESEARCHER.value: ResearcherAgent(),
            AgentType.DEBUGGER.value:   DebuggerAgent(),
        }
        self.vector_mem  = VectorMemory(persist_path=CHROMA_PATH, ollama_host=OLLAMA_HOST)
        self.state:   SystemState | None = None
        self._project: str = "default"
        # Clarification flow: server sets this future when user answers
        self._clarification_future: asyncio.Future | None = None

    # ── Ana giriş noktası ────────────────────────────────────────────────

    @staticmethod
    def _project_slug(goal: str, session_id: str) -> str:
        """Goal'dan kısa, dosya-güvenli bir proje ismi türet."""
        slug = re.sub(r"[^\w\s-]", "", goal.lower())
        slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
        return f"{slug[:30]}_{session_id}" if slug else session_id

    async def run(self, goal: str, context: str = "") -> str:
        session_id       = str(uuid.uuid4())[:8]
        self.state       = SystemState(session_id=session_id, goal=goal)
        self._project    = self._project_slug(goal, session_id)
        t_start          = time.perf_counter()

        console.print(Panel(
            f"[bold]Hedef:[/bold] {goal}",
            title=f"[bold blue]⚙ Agent System[/bold blue] [dim](oturum: {session_id})[/dim]",
            border_style="blue",
        ))

        # 1. Vector Memory: benzer geçmiş bağlamı çek (emit'ten önce — memory_recalled bayrağı için)
        past_ctx = await self.vector_mem.recall(goal)
        memory_recalled = bool(past_ctx)
        if past_ctx:
            console.print("[dim]📚 Benzer geçmiş oturum bulundu.[/dim]")
            context = (past_ctx + "\n\n" + context).strip() if context else past_ctx

        await self._emit(wrap("session.start", {
            "session_id":      session_id,
            "goal":            goal,
            "memory_recalled": memory_recalled,
        }))

        # 1b. Clarification check — Mila gerçekten belirsizse sorar
        questions = await self.supervisor.check_clarification(goal, context, emit=self._emit)
        if questions:
            console.print(
                f"\n  [bold blue]💬 Mila[/bold blue]: "
                f"Hedef belirsiz — {len(questions)} soru soruyorum..."
            )
            loop = asyncio.get_running_loop()
            self._clarification_future = loop.create_future()
            await self._emit(wrap("supervisor.clarification_needed", {
                "session_id": session_id,
                "questions":  questions,
            }))
            try:
                answers = await asyncio.wait_for(
                    asyncio.shield(self._clarification_future),
                    timeout=300,   # 5 dakika içinde cevap gelmezse devam
                )
                # Cevapları context'e ekle
                qa_lines = "\n".join(
                    f"Q: {q}\nA: {a}"
                    for q, a in zip(questions, answers)
                    if a and str(a).strip()
                )
                if qa_lines:
                    context = (
                        ("[USER CLARIFICATIONS]\n" + qa_lines + "\n\n" + context)
                        .strip()
                    )
                    console.print(
                        f"  [blue]  ✓ Yanıtlar alındı → context zenginleştirildi[/blue]"
                    )
            except asyncio.TimeoutError:
                console.print("  [yellow]  ⚠ Clarification timeout — devam ediliyor...[/yellow]")
            finally:
                self._clarification_future = None

        # 2. Supervisor → Plan (available_models'ı ilet ki model seçimi yapabilsin)
        ollama_mods = await get_ollama_models()
        available_models = [f"ollama:{m}" for m in ollama_mods]
        # Cloud modelleri de ekle (varsa)
        from config import GOOGLE_API_KEY, ANTHROPIC_API_KEY
        if GOOGLE_API_KEY and GOOGLE_API_KEY not in ("", "your_gemini_api_key_here"):
            available_models += [
                "gemini:gemini-2.5-flash-preview-04-17",
                "gemini:gemini-2.0-flash",
            ]
        if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY not in ("", "your_anthropic_api_key_here"):
            available_models.append("claude:claude-sonnet-4-6")

        plan = await self.supervisor.create_plan(
            goal,
            context,
            emit             = self._emit,
            available_models = available_models,
        )
        self.state.plan = plan

        # Belt-and-suspenders: inject extracted constraint into every task's context
        # so even if Mila's JSON omitted it, agents always see it.
        constraint = self._extract_constraint(goal)
        if constraint:
            for task in plan.tasks:
                if constraint not in (task.context or ""):
                    task.context = (
                        constraint + "\n\n" + task.context
                        if task.context
                        else constraint
                    )

        self._display_plan(plan)

        # 3. Planı yürüt
        results = await self._execute_plan(plan)

        # 3b. Revision loop: reviewer CHANGES_REQUIRED → coder re-run (max 3 iter)
        results = await self._revision_loop(plan, results, goal)

        # 3c. Neo auto-trigger: CRITICAL hatalar → debugger devreye girer
        results = await self._neo_auto_trigger(results)

        self.state.results = {r.task_id: r for r in results}

        # 4. Supervisor → Değerlendir
        review = await self.supervisor.review_results(goal, results, emit=self._emit)
        self.state.final_review = review

        elapsed = time.perf_counter() - t_start
        success_n = sum(1 for r in results if r.success)
        fail_n    = len(results) - success_n

        # 5. Vector Memory: oturumu kaydet
        await self.vector_mem.save(session_id, goal, review)

        await self._emit(wrap("session.complete", {
            "session_id":   session_id,
            "duration_s":   round(elapsed, 2),
            "success_count": success_n,
            "fail_count":   fail_n,
            "final_review": review[:500],
        }))

        console.print(Panel(
            review,
            title=f"[bold green]✅ Mila — Nihai Değerlendirme[/bold green] [dim]({elapsed:.1f}s)[/dim]",
            border_style="green",
        ))
        return review

    # ── Tech constraint extractor ────────────────────────────────────────

    @staticmethod
    def _extract_constraint(goal: str) -> str:
        """
        Kullanıcının hedefinden teknoloji kısıtlarını çıkarır.
        Örnek: "HTML/CSS/JS only" veya "framework kullanma"
        Boş string döndürürse kısıt yok demektir.
        """
        patterns = [
            r"\b(vanilla\s+(?:javascript|js|python))\b",
            r"\b(plain\s+(?:html|css|js|javascript|python))\b",
            r"\b(no\s+(?:framework|frameworks|libraries|library|react|vue|angular|flask|django|fastapi))\b",
            r"\b(html\s*/?\s*css\s*/?\s*js(?:on)?\s*(?:only|sadece|kullan)?)\b",
            r"\bsadece\s+(?:html|css|js|javascript|python)\b",
            r"\bframework\s+kullanma\b",
            r"\b(?:pure|only)\s+(?:html|css|js|javascript|python)\b",
        ]
        found = []
        g = goal.lower()
        for pat in patterns:
            m = re.search(pat, g, re.IGNORECASE)
            if m:
                found.append(m.group(0).strip())
        if not found:
            return ""
        combined = ", ".join(dict.fromkeys(found))  # deduplicate
        return f"TECHNOLOGY CONSTRAINT (non-negotiable): {combined}. Do NOT use any framework, library, or tool outside this scope."

    # ── Revision loop ────────────────────────────────────────────────────

    async def _revision_loop(
        self,
        plan: ExecutionPlan,
        results: list[AgentResult],
        goal: str,
        max_iterations: int = 3,
    ) -> list[AgentResult]:
        """
        Reviewer CHANGES_REQUIRED veya REJECTED dönerse:
          1. Reviewer feedback'ini al
          2. Coder'ı review feedback + orijinal kod ile yeniden çalıştır
          3. Reviewer'ı tekrar çalıştır
          4. Max `max_iterations` kez tekrarla
        """
        for iteration in range(max_iterations):
            # Reviewer sonuçlarını bul
            reviewer_results = [
                r for r in results
                if r.agent_type == AgentType.REVIEWER and r.success
            ]
            if not reviewer_results:
                break

            rev = reviewer_results[-1]  # En son reviewer çıktısı
            verdict = "APPROVED"
            if "CHANGES_REQUIRED" in rev.output:
                verdict = "CHANGES_REQUIRED"
            elif "REJECTED" in rev.output:
                verdict = "REJECTED"

            if verdict == "APPROVED":
                break

            console.print(
                f"\n  [yellow]🔄 Rex: {verdict} — "
                f"Revizyon turu {iteration + 1}/{max_iterations} başlıyor...[/yellow]"
            )
            await self._emit(wrap("revision.start", {
                "iteration": iteration + 1,
                "verdict":   verdict,
            }))

            # Coder çıktısını bul
            coder_results = [
                r for r in results
                if r.agent_type == AgentType.CODER and r.success
            ]
            if not coder_results:
                break

            original_code = coder_results[-1].output[:MAX_CTX_CHARS]

            # Yeni coder task: review feedback + orijinal kod
            fix_task = Task(
                id=f"t_fix_{iteration + 1}",
                type=AgentType.CODER,
                description=(
                    f"Fix ALL issues found by the reviewer. "
                    f"Goal: {goal[:150]}"
                ),
                context=(
                    f"[REVIEWER FEEDBACK — Fix every issue listed]\n"
                    f"{rev.output[:3000]}\n\n"
                    f"[ORIGINAL CODE — Apply fixes here]\n"
                    f"{original_code}"
                ),
                dependencies=[],
                parallel_group=99,
            )

            fix_result = await self._run_task(fix_task, {})
            if not fix_result.success:
                break
            results.append(fix_result)

            # Yeni reviewer task
            re_review_task = Task(
                id=f"t_rereview_{iteration + 1}",
                type=AgentType.REVIEWER,
                description=f"Re-review the fixed code. Goal: {goal[:100]}",
                context=fix_result.output[:MAX_CTX_CHARS],
                dependencies=[],
                parallel_group=99,
            )
            re_review_result = await self._run_task(re_review_task, {})
            if re_review_result.success:
                results.append(re_review_result)

        return results

    # ── Neo auto-trigger ─────────────────────────────────────────────────

    async def _neo_auto_trigger(self, results: list[AgentResult]) -> list[AgentResult]:
        """
        Reviewer çıktısında 🔴 [CRITICAL] varsa Neo (Debugger) devreye girer.
        """
        critical_pattern = re.compile(r"🔴\s*\[CRITICAL\]")
        reviewer_results = [
            r for r in results
            if r.agent_type == AgentType.REVIEWER and r.success
        ]
        if not reviewer_results:
            return results

        rev = reviewer_results[-1]
        criticals = critical_pattern.findall(rev.output)
        if not criticals:
            return results

        console.print(
            f"\n  [bold red]🐛 Neo (Debugger): "
            f"{len(criticals)} kritik hata tespit edildi — devreye giriyor...[/bold red]"
        )
        await self._emit(wrap("neo.triggered", {"critical_count": len(criticals)}))

        # Coder çıktısunu bul
        coder_results = [
            r for r in results
            if r.agent_type == AgentType.CODER and r.success
        ]
        code_ctx = coder_results[-1].output[:MAX_CTX_CHARS] if coder_results else ""

        debug_task = Task(
            id="t_neo_auto",
            type=AgentType.DEBUGGER,
            description="Fix all CRITICAL issues found by the reviewer.",
            context=(
                f"[CRITICAL ISSUES FROM REVIEWER]\n"
                f"{rev.output[:2000]}\n\n"
                f"[CODE TO FIX]\n"
                f"{code_ctx}"
            ),
            dependencies=[],
            parallel_group=99,
        )
        debug_result = await self._run_task(debug_task, {})
        if debug_result.success:
            results.append(debug_result)

        return results

    # ── Plan yürütme ─────────────────────────────────────────────────────

    async def _execute_plan(self, plan: ExecutionPlan) -> list[AgentResult]:
        results:   list[AgentResult]      = []
        completed: dict[str, AgentResult] = {}

        groups: dict[int, list[Task]] = defaultdict(list)
        for task in plan.tasks:
            groups[task.parallel_group].append(task)

        for gid in sorted(groups.keys()):
            ready = [t for t in groups[gid] if self._deps_ok(t, completed)]

            if not ready:
                console.print(f"  [yellow]⚠ Grup {gid}: bağımlılıklar karşılanmadı.[/yellow]")
                continue

            await self._emit(wrap("group.start", {"group_id": gid, "count": len(ready)}))

            if len(ready) == 1:
                r = await self._run_task(ready[0], completed)
                results.append(r)
                completed[r.task_id] = r
            else:
                console.print(
                    f"\n  [bold]▶ Grup {gid}: {len(ready)} görev paralel çalışıyor...[/bold]"
                )
                sem = asyncio.Semaphore(MAX_PARALLEL)

                async def _guarded(t: Task) -> AgentResult:
                    async with sem:
                        return await self._run_task(t, completed)

                group_r = await asyncio.gather(*[_guarded(t) for t in ready])
                for r in group_r:
                    results.append(r)
                    completed[r.task_id] = r

        return results

    def _deps_ok(self, task: Task, done: dict[str, AgentResult]) -> bool:
        return all(dep in done and done[dep].success for dep in task.dependencies)

    # ── Tek görev yürütme ────────────────────────────────────────────────

    async def _run_task(
        self,
        task:      Task,
        completed: dict[str, AgentResult],
    ) -> AgentResult:
        # Bağımlılık bağlamını enjekte et
        # gemma4:26b 128K ctx → context limitlerini çok daha yüksek tutabiliriz
        _CTX_LIMIT = {
            "coder":    10_000,  # Aria'nın tam spec'i gitsin, kesinlikle kısaltma
            "reviewer": 14_000,  # Kenji'nin tüm kodunu görmesi şart
            "tester":   12_000,  # Test yazabilmek için tam kodu görmesi gerekir
            "debugger": 14_000,  # Debug için tam context kritik
        }
        ctx_limit = _CTX_LIMIT.get(task.type.value, MAX_CTX_CHARS)

        if task.dependencies:
            dep_texts = []
            for dep_id in task.dependencies:
                if dep_id in completed and completed[dep_id].output:
                    dep_result = completed[dep_id]
                    snippet    = dep_result.output[:ctx_limit]
                    agent_type = dep_result.agent_type.value
                    label = {
                        "researcher": "RESEARCHER SPEC (Aria)",
                        "coder":      "IMPLEMENTATION (Kenji)",
                        "reviewer":   "REVIEW REPORT (Rex)",
                        "tester":     "TEST SUITE (Zara)",
                        "debugger":   "DEBUG REPORT (Neo)",
                    }.get(agent_type, dep_id)
                    dep_texts.append(f"══ {label} ══\n{snippet}")
            if dep_texts:
                injected     = "\n\n".join(dep_texts)
                task.context = (
                    (task.context + "\n\n" + injected).strip()
                    if task.context else injected
                )

        task.status = TaskStatus.RUNNING
        agent       = self._agents.get(task.type.value)

        if agent is None:
            task.status = TaskStatus.FAILED
            result = AgentResult(
                task_id    = task.id,
                agent_type = task.type,
                success    = False,
                output     = "",
                errors     = [f"Ajan bulunamadı: {task.type.value}"],
            )
            await self._emit(wrap("task.error", {
                "task_id": task.id, "error": result.errors[0]
            }))
            return result

        # ── Model Override: Supervisor'ın seçimi varsa geçici olarak uygula ──
        _orig_llm   = None
        _orig_label = None
        if task.model_override:
            try:
                parts = task.model_override.split(":", 1)
                prov  = parts[0] if len(parts) == 2 else "ollama"
                mdl   = parts[1] if len(parts) == 2 else parts[0]
                # Şu an kullanılan modelden farklıysa değiştir
                if agent._model_label != f"{prov}:{mdl}":
                    cfg_temp = MODELS.get(task.type.value, MODELS["fast"]).get("temperature", 0.1)
                    new_llm  = create_llm(prov, mdl, cfg_temp)
                    _orig_llm   = agent.llm
                    _orig_label = agent._model_label
                    agent.llm         = new_llm
                    agent._model_label = f"{prov}:{mdl}"
                    console.print(
                        f"  [cyan]🔀 [{task.type.value}] Supervisor model seçimi: "
                        f"[bold]{prov}:{mdl}[/bold][/cyan]"
                    )
                    # UI'ya bildir
                    await self._emit(wrap("task.model_override", {
                        "task_id":    task.id,
                        "agent_type": task.type.value,
                        "model":      f"{prov}:{mdl}",
                    }))
            except Exception as exc:
                console.print(f"  [yellow]⚠ Model override uygulanamadı ({task.model_override}): {exc}[/yellow]")

        t0 = time.perf_counter()
        try:
            # ── Watchdog: akış izleyicisi ───────────────────────────────────────
            watchdog     = Watchdog(emit=self._emit)
            wrapped_emit = watchdog.make_emit_wrapper(self._emit)

            result = await watchdog.guard(
                task_id    = task.id,
                agent_type = task.type.value,
                coro       = agent.execute(task, emit=wrapped_emit),
            )
        except WatchdogCancelled as exc:
            result = AgentResult(
                task_id    = task.id,
                agent_type = task.type,
                success    = False,
                output     = "",
                errors     = [f"Watchdog cancelled: {exc.reason}"],
            )
            console.print(
                f"  [bold red]🐕 Watchdog: [{task.type.value}] iptal edildi — {exc.reason}[/bold red]"
            )
        except asyncio.CancelledError:
            raise
        finally:
            # Orijinal modeli geri yükle (başka task'lar etkilenmesin)
            if _orig_llm is not None:
                agent.llm          = _orig_llm
                agent._model_label = _orig_label
        result.duration_s = time.perf_counter() - t0

        task.status     = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
        task.result     = result.output[:400] if result.success else None
        task.error      = result.errors[0] if result.errors else None

        # Coder çıktısından dosyaları otomatik kaydet
        if result.success and task.type == AgentType.CODER and result.output:
            try:
                saved = await save_code_files(result.output, self._project)
                if saved:
                    result.saved_files = saved
                    console.print(
                        f"  [dim cyan]📁 {len(saved)} dosya kaydedildi → workspace/{self._project}/[/dim cyan]"
                    )
                    await self._emit(wrap("workspace.files_saved", {
                        "project":    self._project,
                        "files":      [str(f) for f in saved],
                        "task_id":    task.id,
                    }))
                    # Kaydedilen dosyaları result.output'a ekle — reviewer/tester görsün
                    file_manifest = "\n".join(f"  • workspace/{self._project}/{Path(f).name}" for f in saved)
                    result.output += f"\n\n[SAVED FILES — workspace/{self._project}/]\n{file_manifest}"
            except Exception as exc:
                console.print(f"  [dim red]⚠ Dosya kaydetme hatası: {exc}[/dim red]")

        await self._emit(wrap("task.complete", {
            "task_id":      task.id,
            "agent_type":   task.type.value,
            "success":      result.success,
            "duration_s":   round(result.duration_s, 2),
            "output_preview": result.output[:200] if result.success else "",
        }))

        icon = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        console.print(
            f"  {icon} [{task.type.value}] '{task.id}' ({result.duration_s:.1f}s)"
        )
        return result

    # ── Plan tablosu (CLI) ───────────────────────────────────────────────

    def _display_plan(self, plan: ExecutionPlan) -> None:
        if plan.analysis:
            console.print(Panel(
                plan.analysis,
                title="[blue]Mila — Görev Analizi[/blue]",
                border_style="blue",
                padding=(0, 1),
            ))

        tbl = Table(title="Yürütme Planı", show_header=True, header_style="bold magenta")
        tbl.add_column("ID",         style="dim", width=10)
        tbl.add_column("Ajan",       width=12)
        tbl.add_column("Açıklama")
        tbl.add_column("Bağımlılık", width=14)
        tbl.add_column("Grup",       width=6, justify="center")

        colors = {"coder": "green", "researcher": "magenta",
                  "reviewer": "yellow", "tester": "cyan", "debugger": "red"}

        for t in plan.tasks:
            c    = colors.get(t.type.value, "white")
            desc = t.description[:65] + "…" if len(t.description) > 65 else t.description
            tbl.add_row(
                t.id,
                f"[{c}]{t.type.value}[/{c}]",
                desc,
                ", ".join(t.dependencies) or "—",
                str(t.parallel_group),
            )
        console.print(tbl)
