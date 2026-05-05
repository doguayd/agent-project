"""
Supervisor Agent — Mila
=======================
Language policy:
  - Understands user input in any language (TR / EN)
  - Internal planning, task descriptions, JSON → English (max LLM efficiency)
  - Final output to the user → always Turkish
  - Specialist agent outputs → English (never shown raw to user)
"""

from __future__ import annotations

import json
import re
import time
import uuid

from rich.console import Console

from agents.base_agent import _filter_think_chunk, _strip_think_blocks
from config import MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from core.memory import ConversationMemory
from core.models import AgentResult, AgentType, ExecutionPlan, Task, TaskStatus

console = Console()

# ─── System Prompt ───────────────────────────────────────────────────────────

_SYSTEM = """\
[PERSONA]
Your name is Mila. You are the chief architect of a universal multi-agent system.
You can handle coding tasks, research, property search, car search, music creation,
OSINT research, financial analysis, and more. You delegate to the right specialist.
"Ambiguity is the enemy of a good plan." — your personal philosophy.
You are calm, strategic, and always see the big picture.

[ROLE]
1. PLAN      — Decompose the user's task into focused, concrete sub-tasks
2. ROUTE     — Assign each sub-task to the most appropriate specialist
3. EVALUATE  — Analyse all specialist outputs critically and honestly
4. SYNTHESISE — Produce a final, ready-to-use response for the user

[SPECIALISTS — CODING]
  researcher  → Requirements analysis, library research, architecture spec, design decisions
  coder       → Production-quality code (Python, JS, TS, Rust, Go, Bash, SQL, etc.)
  reviewer    → Code review: correctness, bugs, security, completeness, best practices
  tester      → Unit / integration / e2e / API tests — runnable test suites
  debugger    → Root-cause analysis, bug fixing, error tracing

[SPECIALISTS — DOMAIN AGENTS]
  Note: These domain agents are handled automatically by the server routing.
  When user asks for these, mention them and the system will handle routing:
  • property  (Lara)  → Real estate search on emlakjet.com
  • car       (Turbo) → Used car search on arabam.com
  • finance   (Nova)  → Stock prices, crypto, currency analysis with yfinance
  • osint     (Sigma) → Username/person search across 3000+ sites using maigret
  • music     (Ziya)  → Local music generation with ACE-Step AI

[ATTACHED FILES / IMAGES]
  When the user attaches a file or image, its content will be included in [CONTEXT].
  Images will be described by a vision model. Use this context to understand the user's intent.
  Text files, code, PDFs → content will be directly included as context.

[COMPLEXITY TIERS — choose the pipeline based on task complexity]
  SIMPLE  (single file, utility, quick script):
    → researcher → coder → reviewer
  STANDARD (web app, REST API, CLI tool with multiple features):
    → researcher → coder → reviewer + tester (parallel)
  COMPLEX (full-stack app, auth system, multi-module project):
    → researcher → coder → reviewer + tester (parallel) → debugger (if issues found)
  VERY COMPLEX (system design, multi-service, framework):
    → researcher (deep spec) → coder → reviewer + tester (parallel) → debugger

[PLANNING RULES]
  - Independent tasks → SAME parallel_group → run concurrently
  - Dependent tasks   → DIFFERENT parallel_group → run sequentially
  - parallel_group: 0, 1, 2, 3 … (lower number runs first)
  - ALWAYS match pipeline to complexity — don't use 4 agents for a 20-line script
  - ALWAYS include researcher for any task involving non-trivial architecture decisions
  - ALWAYS include reviewer when coder is in the plan
  - Include tester when: the task produces reusable code (functions, classes, API endpoints)
  - ALL JSON fields (analysis, description, context) MUST be in English — no exceptions
  - Task descriptions must be SPECIFIC and DETAILED, mentioning concrete features
  - Never write generic phrases like "plan the project" or "design the system" alone

[LANGUAGE RULE — CRITICAL]
  - Understand user input in any language (Turkish, English, or mixed)
  - All internal reasoning, planning JSON, and task descriptions → English
  - When producing the FINAL RESPONSE for the user → ALWAYS respond in Turkish
  - Specialist agents output in English; you translate/synthesise into Turkish for the user
  - Never mix languages in the final response: it must be 100% Turkish

[OUTPUT]
When creating a plan: respond with ONLY valid JSON — no markdown, no explanation.
When evaluating results: respond in Turkish, specific and actionable."""


class SupervisorAgent:

    def __init__(self, memory: ConversationMemory | None = None) -> None:
        self.memory = memory or ConversationMemory(agent_name="supervisor")
        cfg         = MODELS["supervisor"]
        try:
            self.llm = create_llm(
                provider    = cfg["provider"],
                model       = cfg["model"],
                temperature = cfg.get("temperature", 0.3),
            )
        except Exception:
            # API key eksik/geçersiz → en iyi yerel modele düş
            import asyncio
            from core.llm_client import auto_select_supervisor
            from config import MODELS as _M
            try:
                provider, model = asyncio.get_event_loop().run_until_complete(
                    auto_select_supervisor()
                )
            except Exception:
                provider, model = "ollama", "llama3.1:8b"
            _M["supervisor"]["provider"] = provider
            _M["supervisor"]["model"]    = model
            cfg = _M["supervisor"]
            self.llm = create_llm(provider, model, cfg.get("temperature", 0.3))
            console.print(f"  [yellow]⚠ Gemini API key bulunamadı → {provider}:{model}[/yellow]")
        self._label = f"{cfg['provider']}:{cfg['model']}"

    def refresh_llm(self) -> None:
        cfg         = MODELS["supervisor"]
        self.llm    = create_llm(cfg["provider"], cfg["model"], cfg.get("temperature", 0.3))
        self._label = f"{cfg['provider']}:{cfg['model']}"

    # ── Core generator ───────────────────────────────────────────────────────

    async def _gen(
        self,
        user_msg:   str,
        emit:       Emitter = noop,
        event_type: str     = "supervisor.stream",
    ) -> str:
        messages = [
            {"role": "system",    "content": _SYSTEM},
            *self.memory.get_as_dicts(last_n=6),
            {"role": "user",      "content": user_msg},
        ]
        console.print(f"    [dim]↳ [supervisor] {self._label}...[/dim]")
        t0         = time.perf_counter()
        full       = ""
        _in_think  = False
        _think_buf = ""

        if emit is not noop:
            try:
                async for chunk in self.llm.stream(messages):
                    full += chunk
                    visible    = _filter_think_chunk(chunk, _think_buf, _in_think)
                    _in_think  = visible[1]
                    _think_buf = visible[2]
                    if visible[0]:
                        await emit(wrap(event_type, {"chunk": visible[0]}))
            except Exception:
                full = await self.llm.generate(messages)
                full = _strip_think_blocks(full)
        else:
            full = await self.llm.generate(messages)
            full = _strip_think_blocks(full)

        console.print(f"    [dim]  ✓ {time.perf_counter() - t0:.1f}s[/dim]")
        self.memory.add("user",      user_msg)
        self.memory.add("assistant", full)
        return full

    # ── Plan creation ────────────────────────────────────────────────────────

    async def create_plan(
        self,
        goal:             str,
        context:          str       = "",
        emit:             Emitter   = noop,
        available_models: list[str] = [],
    ) -> ExecutionPlan:
        console.print("\n[bold blue]🧠 Mila[/bold blue]: Analysing task and building plan...")
        await emit(wrap("supervisor.plan_start", {}))

        # ── Model seçim bloğu ──────────────────────────────────────────────
        if available_models:
            models_list = "\n".join(f"  - {m}" for m in available_models)
            model_rule = f"""
[RULE 5 — OPTIONAL MODEL SELECTION PER TASK]
You may add a "model" field to each task to override the default agent LLM.
Use this only when a different model would significantly improve that task's quality.

Available models:
{models_list}

Selection guidance:
  - researcher / debugger tasks  → prefer reasoning/general models (e.g. qwen3:14b, gemma4:26b)
  - coder tasks (writing code)   → prefer coding-specialist models (e.g. qwen2.5-coder:14b)
  - reviewer / tester tasks      → prefer coding-specialist models (e.g. qwen2.5-coder:14b)
  - If the coder task is NOT pure code writing (e.g. diagnostic, audit, analysis) → use a general model
  - Omit the "model" field entirely if the default is appropriate.

Format: "provider:model_name"  e.g. "ollama:qwen3:14b"
"""
            model_field_doc = '      "model": "ollama:qwen3:14b",   (OPTIONAL — omit if default is fine)\n'
        else:
            model_rule = ""
            model_field_doc = ""

        prompt = f"""You are Mila. Create a precise execution plan for the task below.

USER GOAL (may be in Turkish or English): {goal}
{f"EXTRA CONTEXT:\\n{context[:800]}" if context else ""}

STRICT RULES — READ CAREFULLY:

[RULE 1 — LANGUAGE]
Every field in the JSON (analysis, description, context) MUST be written in English.
Never use Turkish, even if the goal was written in Turkish. Translate everything.

[RULE 2 — TASK DESCRIPTIONS MUST BE SPECIFIC]
The "description" field for EVERY task must be a concrete, detailed instruction.
Bad:  "Plan and design the project"
Good: "Research requirements for an e-commerce shopping website with product listing,
       user authentication (register/login), shopping cart, and checkout. Define the
       HTML/CSS/JS component structure, data models for products and cart, and UI layout."

The researcher's task description must include ALL key features extracted from the user goal.
The coder's task description must say exactly what to build, referencing the features.

[RULE 3 — TECHNOLOGY CONSTRAINTS]
If the goal contains a tech constraint ("HTML/CSS/JS only", "no frameworks", "vanilla JS",
"sadece HTML", "framework kullanma", "pure Python", etc.):
  - Extract it as: "CONSTRAINT: Use plain HTML/CSS/JS only. No Vue, React, or any framework."
  - Put this constraint at the START of the context field of EVERY task.
If no constraint is mentioned, leave context as "".

[RULE 4 — GOAL ECHO IN RESEARCHER DESCRIPTION]
The researcher's description must restate the full goal in concrete technical terms.
Do not use generic phrases like "plan the project" or "define requirements" alone.
{model_rule}
Respond with ONLY valid JSON — no markdown fences, no explanation, no prose:
{{
  "analysis": "1-2 sentence English summary of what will be built and key features",
  "tasks": [
    {{
      "id": "t1",
      "type": "researcher",
{model_field_doc}      "description": "Research and define all requirements for <specific thing from goal>. Include: <list key features>. Determine component structure, data models, and implementation approach.",
      "context": "<CONSTRAINT if any, else empty string>",
      "dependencies": [],
      "parallel_group": 0
    }},
    {{
      "id": "t2",
      "type": "coder",
{model_field_doc}      "description": "Implement <specific thing> with <list key features>. Produce complete, runnable code with all features, real content, and full styling.",
      "context": "<CONSTRAINT if any, else empty string>",
      "dependencies": ["t1"],
      "parallel_group": 1
    }}
  ]
}}

Allowed type values: researcher, coder, reviewer, tester, debugger
Tasks in the same parallel_group with no shared dependencies run CONCURRENTLY."""

        raw  = await self._gen(prompt, emit, event_type="supervisor.stream")
        plan = self._parse(goal, raw)
        plan = self._enrich_plan(goal, plan)

        await emit(wrap("plan.created", {
            "analysis":     plan.analysis,
            "tasks": [
                {
                    "id":             t.id,
                    "type":           t.type.value,
                    "description":    t.description,
                    "dependencies":   t.dependencies,
                    "parallel_group": t.parallel_group,
                    "model_override": t.model_override,
                }
                for t in plan.tasks
            ],
            "total_groups": plan.total_groups,
        }))

        console.print(f"  [blue]→ {len(plan.tasks)} tasks, {plan.total_groups} parallel groups.[/blue]")
        return plan

    # ── Plan parser ──────────────────────────────────────────────────────────

    def _parse(self, goal: str, raw: str) -> ExecutionPlan:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return self._fallback(goal)
        try:
            data  = json.loads(m.group())
            tasks = []
            for t in data.get("tasks", []):
                try:
                    atype = AgentType(t.get("type", "coder"))
                except ValueError:
                    atype = AgentType.CODER
                tasks.append(Task(
                    id             = t.get("id", str(uuid.uuid4())[:6]),
                    type           = atype,
                    description    = t.get("description", ""),
                    context        = t.get("context", ""),
                    dependencies   = t.get("dependencies", []),
                    parallel_group = int(t.get("parallel_group", 0)),
                    model_override = t.get("model") or None,
                ))
            if not tasks:
                return self._fallback(goal)
            groups = max(t.parallel_group for t in tasks) + 1
            return ExecutionPlan(
                goal             = goal,
                analysis         = data.get("analysis", ""),
                tasks            = tasks,
                total_groups     = groups,
                estimated_agents = len(tasks),
            )
        except Exception:
            return self._fallback(goal)

    @staticmethod
    def _goal_to_english_summary(goal: str) -> str:
        """
        Convert a (possibly Turkish) goal into a short, clean English-safe descriptor.
        Uses ASCII keyword extraction to avoid injecting Turkish into agent descriptions.
        Falls back to 'the requested project' if goal is entirely non-ASCII.
        """
        # Extract ASCII words only (safe for English prompts)
        ascii_words = re.findall(r"[a-zA-Z]{3,}", goal)
        if ascii_words:
            return " ".join(ascii_words[:12])
        # Fully non-ASCII (Turkish) — return generic safe descriptor
        # Try to detect common Turkish keywords and map them
        lower = goal.lower()
        hints = []
        kw_map = [
            (["web sit", "website", "site"],       "website"),
            (["alışveriş", "alisveris", "shop"],   "e-commerce shopping website"),
            (["tatil", "tur", "otel", "seyahat"],  "travel and tourism website"),
            (["blog"],                              "blog website"),
            (["portföy", "portfolio"],              "portfolio website"),
            (["oyun", "game"],                      "game"),
            (["uygulama", "app", "application"],    "application"),
            (["api"],                               "REST API"),
            (["html", "css", "js"],                "HTML/CSS/JS web page"),
            (["python", "flask", "django"],        "Python web application"),
        ]
        for keys, label in kw_map:
            if any(k in lower for k in keys):
                hints.append(label)
        if hints:
            return " and ".join(hints)
        return "the requested project"

    # Generic filler phrases that Mila sometimes produces instead of real descriptions
    _VAGUE_PHRASES = {
        "plan the project", "design the system", "implement the project",
        "build the app", "code the project", "create the application",
        "develop the system", "write the code", "make the app",
        "implement the task", "complete the task", "handle the task",
    }

    def _enrich_plan(self, goal: str, plan: ExecutionPlan) -> ExecutionPlan:
        """
        Post-processing:
        1. Replace vague task descriptions with goal-specific English ones.
           A description is vague ONLY if it is very short (<40 chars) OR contains
           known filler phrases. We do NOT use word-overlap with the goal because
           Turkish goals produce garbled ASCII fragments that never match English descriptions,
           causing good supervisor descriptions to be incorrectly overridden.
        2. If the plan has a coder task but NO reviewer, inject a reviewer task automatically.
        """
        safe_goal = self._goal_to_english_summary(goal)

        # ── Fix vague descriptions ────────────────────────────────────────────
        for task in plan.tasks:
            desc = (task.description or "").strip()
            desc_lower = desc.lower()

            is_vague = (
                len(desc) < 40
                or any(phrase in desc_lower for phrase in self._VAGUE_PHRASES)
            )

            if is_vague:
                if task.type == AgentType.RESEARCHER:
                    task.description = (
                        f"Research all technical requirements for: {safe_goal}. "
                        "Define: tech stack, component structure, data models, UI layout, "
                        "color scheme, typography, and key features. Be exhaustive — "
                        "the coder relies entirely on this output."
                    )
                elif task.type == AgentType.CODER:
                    task.description = (
                        f"Implement a complete, production-ready: {safe_goal}. "
                        "Include all requested features, vibrant CSS design, real content, "
                        "working JS logic. No placeholders, no stubs, no gray boxes."
                    )
                elif task.type == AgentType.REVIEWER:
                    task.description = (
                        f"Review the implementation of: {safe_goal}. "
                        "Check for bugs, security issues, performance problems, and missing features."
                    )
                elif task.type == AgentType.TESTER:
                    task.description = (
                        f"Write comprehensive tests for: {safe_goal}. "
                        "Cover all core features, edge cases, and error scenarios."
                    )
                elif task.type == AgentType.DEBUGGER:
                    task.description = (
                        f"Debug and fix all issues in the implementation of: {safe_goal}."
                    )

        # ── Auto-inject reviewer if missing ──────────────────────────────────
        types_in_plan = {t.type for t in plan.tasks}
        has_coder    = AgentType.CODER    in types_in_plan
        has_reviewer = AgentType.REVIEWER in types_in_plan

        if has_coder and not has_reviewer:
            # Find the coder task to get its id for dependency
            coder_ids = [t.id for t in plan.tasks if t.type == AgentType.CODER]
            max_group = max(t.parallel_group for t in plan.tasks)
            reviewer_group = max_group + 1
            plan.tasks.append(Task(
                id             = "t_rev_auto",
                type           = AgentType.REVIEWER,
                description    = (
                    f"Review the implementation of: {safe_goal}. "
                    "Identify bugs, missing features, security issues, poor styling, "
                    "placeholder content, and any code that doesn't meet requirements."
                ),
                dependencies   = coder_ids,
                parallel_group = reviewer_group,
            ))
            plan.total_groups     = reviewer_group + 1
            plan.estimated_agents = len(plan.tasks)

        return plan

    # ── Auto-routing classifier ──────────────────────────────────────────────

    async def classify_task(self, goal: str) -> str:
        """
        Görevi hızlıca sınıflandır:
        Returns: 'code' | 'property' | 'car' | 'finance' | 'osint' | 'music' | 'browser'

        Önce kural tabanlı hızlı kontrol, sonra LLM.
        """
        lower = goal.lower()

        # ── Hızlı kural tabanlı sınıflandırma ───────────────────────────────
        # Browser: web automation görevleri
        _browser_kw = [
            "aç", "git", "bul ve tıkla", "chrome", "tarayıcı", "siteye git",
            "web'de", "internette", "web'den", "sitesinde", "n11", "hepsiburada",
            "trendyol", "amazon", "sahibinden", "başvur", "iş başvuru",
            "formu doldur", "kayıt ol", "satın al", "sipariş ver",
            "rezervasyon", "bilet", "uçak", "otel book", "booking",
            "linkini aç", "url'e git", "web sitesini",
            "browse", "open chrome", "navigate", "click on", "fill form",
        ]
        _browser_strong = [
            "benim için", "bana", "yerime", "n11'den", "trendyol'dan",
            "hepsiburada'dan", "amazonda", "siteden bul", "sayfasına git",
        ]
        # Browser eğer hem bir eylem hem bir web hedefi varsa
        if any(k in lower for k in _browser_strong) and any(
            k in lower for k in ["bul", "ara", "aç", "git", "başvur", "al", "satın", "izle"]
        ):
            return "browser"
        if any(k in lower for k in _browser_kw):
            return "browser"

        # Emlak
        _prop_kw = ["daire", "kiralık", "satılık", "emlak", "konut", "ilan",
                    "m2", "metro", "apartment", "flat", "property", "rent", "estate"]
        if any(k in lower for k in _prop_kw):
            return "property"

        # Araç
        _car_kw = ["araç", "araba", "otomobil", "km", "dizel", "benzin",
                   "hibrit", "motor", "sedan", "suv", "binek", "ikinci el",
                   "car", "vehicle", "bmw", "mercedes", "toyota", "honda", "ford",
                   "volkswagen", "renault", "hyundai", "audi"]
        if any(k in lower for k in _car_kw):
            return "car"

        # Finans
        _fin_kw = ["hisse", "borsa", "kripto", "bitcoin", "ethereum", "dolar",
                   "euro", "döviz", "fiyat", "piyasa", "altın", "faiz",
                   "stock", "crypto", "finance", "market", "usd", "eur",
                   "nasdaq", "bist", "aapl", "tsla", "nvda", "garan", "thyao"]
        if any(k in lower for k in _fin_kw):
            return "finance"

        # OSINT
        _osint_kw = ["kullanıcı adı", "username", "osint", "profil ara",
                     "sosyal medya bul", "instagram hesap", "twitter hesap",
                     "maigret", "person search", "find profile"]
        if any(k in lower for k in _osint_kw):
            return "osint"

        # Müzik
        _music_kw = ["müzik", "şarkı", "melodl", "piyano", "gitar", "beat",
                     "enstrüman", "ambient", "tempo", "music", "song", "melody",
                     "ace-step", "üret", "compose"]
        if any(k in lower for k in _music_kw) and any(
            k in lower for k in ["üret", "yap", "oluştur", "compose", "create", "generate"]
        ):
            return "music"

        # Kod (default)
        _code_kw = ["yaz", "kod", "uygulama", "script", "api", "web site",
                    "python", "javascript", "html", "css", "flask", "django",
                    "react", "database", "sql", "function", "class", "implement",
                    "build", "create", "develop", "write", "program"]
        if any(k in lower for k in _code_kw):
            return "code"

        # Belirsiz → LLM'e sor (hızlı)
        prompt = f"""Classify this task into ONE category (reply with ONLY the category name):

Task: {goal}

Categories:
- code: programming, coding, writing software, creating apps/scripts/APIs
- property: real estate, apartment search, rent/buy house
- car: used car search, vehicle lookup
- finance: stocks, crypto, currency prices, market data
- osint: username search, person search across social media
- music: music generation, composing
- browser: anything requiring web browsing, visiting websites, clicking, filling forms, shopping, job applications

Reply with ONLY one word: code, property, car, finance, osint, music, or browser"""

        try:
            raw = await self.llm.generate([{"role": "user", "content": prompt}])
            raw = _strip_think_blocks(raw).strip().lower().split()[0]
            if raw in {"code", "property", "car", "finance", "osint", "music", "browser"}:
                return raw
        except Exception:
            pass

        return "code"  # default fallback

    def _fallback(self, goal: str) -> ExecutionPlan:
        tasks = [
            Task(id="t_res",  type=AgentType.RESEARCHER,
                 description=f"Research requirements and architecture for: {goal}",
                 parallel_group=0),
            Task(id="t_code", type=AgentType.CODER,
                 description=f"Implement: {goal}",
                 dependencies=["t_res"], parallel_group=1),
            Task(id="t_rev",  type=AgentType.REVIEWER,
                 description="Review the implementation for bugs, security, and quality",
                 dependencies=["t_code"], parallel_group=2),
            Task(id="t_test", type=AgentType.TESTER,
                 description="Write comprehensive tests for the implementation",
                 dependencies=["t_code"], parallel_group=2),
        ]
        return ExecutionPlan(goal=goal, tasks=tasks, total_groups=3, estimated_agents=4)

    # ── Result evaluation ────────────────────────────────────────────────────

    async def review_results(
        self,
        goal:    str,
        results: list[AgentResult],
        emit:    Emitter = noop,
    ) -> str:
        console.print("\n[bold blue]🔍 Mila[/bold blue]: Evaluating all results...")
        await emit(wrap("supervisor.review_start", {}))

        parts = []
        for r in results:
            status  = "SUCCESS" if r.success else "FAILED"
            snippet = r.output[:3500] + ("…" if len(r.output) > 3500 else "")
            parts.append(f"══ {r.agent_type.value.upper()} [{r.task_id}] — {status} ══\n{snippet}")
        summary = "\n\n".join(parts)

        prompt = f"""You are Mila. Evaluate the outputs below and write a final report for the user.

ORIGINAL GOAL: {goal}

AGENT OUTPUTS:
{summary}

══ ABSOLUTE RULES — VIOLATIONS ARE NOT ACCEPTABLE ══

[RULE 1 — NEVER REWRITE CODE]
The "Nihai Çıktı" section MUST contain code copied VERBATIM from the CODER or DEBUGGER agent.
Do NOT rewrite, translate, modify, or paraphrase any code.
Do NOT generate new code of your own — only copy exactly what agents produced.
HTML content inside code stays in whatever language the coder wrote it.

[RULE 2 — LANGUAGE]
All text OUTSIDE of code blocks must be 100% Turkish.
Code blocks are reproduced as-is.

[RULE 3 — HONEST QUALITY EVALUATION]
Carefully read ALL agent outputs before writing your evaluation.
Check:
  - Did the CODER produce complete, running code? Any TODO/stub/placeholder → "Kısmi"
  - Did the REVIEWER raise CRITICAL or MAJOR issues? → mention them in ⚠️
  - Did the TESTER write actual tests? Were they for the right code?
  - Did the DEBUGGER fix any issues? Use the DEBUGGER's output as the final code if available.
Status rules:
  "Başarılı"  → Code is complete, reviewer approved or only minor issues, runs as-is
  "Kısmi"     → Any TODO/stub/incomplete section, or MAJOR reviewer issues remain
  "Başarısız" → Coder produced nothing useful, or CRITICAL security/crash issues unfixed

[RULE 4 — USE BEST OUTPUT]
If DEBUGGER ran and produced fixed code → use debugger's code in "Nihai Çıktı".
If REVIEWER produced a FIXED CODE section → mention it but don't include (too long).
Always prefer the most recent, most complete version of the code.

[RULE 5 — NO FABRICATION]
Never invent code, features, or analysis not present in agent outputs.
If something is missing, list it under ⚠️ exactly.

══ OUTPUT STRUCTURE ══
Write your response in this exact structure (Turkish text, verbatim code):

1. 🎯 Genel Durum — Başarılı / Kısmi / Başarısız — tek cümle özet
2. ✅ Tamamlananlar — Her ajanın yaptığı iş madde madde (spesifik, "iyi bir iş çıkardı" gibi muğlak yazma)
3. 💡 Nihai Çıktı — Kodun en son ve en iyi halini OLDUĞU GİBİ yapıştır. Uzunsa sadece ana dosyayı koy ve "Workspace'e kaydedildi" yaz.
4. ⚠️ Eksikler / Sorunlar — Her biri spesifik (varsa; yoksa bu bölümü atla)
5. 🔜 Önerilen Sonraki Adımlar — Kullanıcının devam edebileceği şeyler (varsa; yoksa atla)"""

        review = await self._gen(prompt, emit, event_type="supervisor.stream")
        await emit(wrap("supervisor.done", {"output": review}))
        return review

    # ── Clarification check ──────────────────────────────────────────────────

    async def check_clarification(
        self,
        goal:    str,
        context: str    = "",
        emit:    Emitter = noop,
    ) -> list[str] | None:
        """
        Hedef gerçekten belirsizse Türkçe soru listesi döndür, netse None.
        Sadece devreye gerektiğinde girer — mükemmeliyetçi değil, pragmatik.

        Returns:
            list[str]  → sorulması gereken 2-4 soru
            None       → hedef yeterince net, direkt planlama yapılabilir
        """
        word_count = len(goal.split())

        # Hızlı geçiş: 10+ kelimelik hedefler genellikle yeterince açık
        # Veya tanınan teknoloji/proje anahtar kelimeleri içeriyorsa geç
        _clear_signals = [
            "html", "css", "javascript", "python", "flask", "fastapi", "django",
            "react", "vue", "api", "rest", "cli", "website", "web site",
            "uygulama", "yap", "oluştur", "yaz", "geliştir", "analiz",
            "oyun", "game", "blog", "portföy", "todo", "chat", "bot",
        ]
        goal_lower = goal.lower()
        has_clear_signal = any(sig in goal_lower for sig in _clear_signals)

        # Eğer yeterince uzun VEYA herhangi bir net sinyal varsa → clarification gerekmez
        # word_count >= 3 + sinyal = "web sitesi yap" gibi kısa ama açık hedefler için yeterli
        if word_count >= 10 or (word_count >= 3 and has_clear_signal):
            return None

        # Çok kısa ve belirsiz → LLM'e sor
        prompt = f"""You are Mila. A user gave you this goal (may be in Turkish or English):
"{goal}"
{f'Extra context: {context[:200]}' if context else ''}

Decide: Is this goal CLEAR ENOUGH to plan immediately, or does it need clarification?

CLEAR ENOUGH criteria (any one is sufficient):
- The output type is obvious (website, API, script, game, etc.)
- Key features OR the general domain are mentioned
- A reasonable developer could start working immediately with sensible assumptions

NEEDS CLARIFICATION criteria (ALL must be true):
- The goal is extremely vague (2-4 words with no obvious domain)
- You genuinely cannot determine what to build or what technology to use
- Making assumptions would very likely produce the wrong thing

Rules:
- Default to CLEAR — only ask when truly necessary
- Never ask about things you can reasonably assume
- Max 3 targeted questions, in Turkish, addressing only critical unknowns

If CLEAR: respond with exactly one word: CLEAR
If NEEDS CLARIFICATION: respond with a JSON array of 2-3 targeted Turkish questions:
["Soru 1?", "Soru 2?", "Soru 3?"]"""

        raw = await self._gen(prompt, noop)  # noop: don't stream this check
        raw = raw.strip()

        # CLEAR ise None döndür
        if raw.upper().startswith("CLEAR") or '"' not in raw:
            return None

        # JSON array'i parse et
        m = re.search(r"\[[\s\S]*?\]", raw)
        if m:
            try:
                questions = json.loads(m.group())
                if isinstance(questions, list) and questions:
                    return [str(q) for q in questions[:3]]
            except Exception:
                pass

        return None  # parse başarısız → direkt planlama yap

    # ── Quick feedback (internal, English ok) ────────────────────────────────

    async def quick_feedback(self, task_desc: str, output: str, emit: Emitter = noop) -> str:
        prompt = (
            f"In 2-3 sentences, evaluate this output:\n"
            f"TASK: {task_desc}\nOUTPUT (first 800 chars): {output[:800]}\n"
            f"Any critical issues?"
        )
        return await self._gen(prompt, emit)
