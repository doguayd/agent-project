"""
Coder Agent — Kenji
===================
Language: English only (inter-agent communication).
Persona : Silent perfectionist. Code is craft — every line intentional.
Model   : qwen2.5-coder:14b (RTX 4090 GPU / CPU fallback)
"""

from __future__ import annotations

import re
from rich.console import Console

from agents.base_agent import BaseAgent
from core.events import Emitter, noop, wrap
from core.models import AgentResult, AgentType, Task
from tools.web_search import quick_search

console = Console()


def _detect_task_type(description: str, context: str) -> str:
    """Görev tipini tespit et: web | api | cli | script | library | general"""
    combined = (description + " " + context).lower()
    if any(k in combined for k in ["html", "css", "website", "webpage", "frontend", "ui", "landing"]):
        return "web"
    if any(k in combined for k in ["rest api", "fastapi", "flask", "django", "endpoint", "route", "http"]):
        return "api"
    if any(k in combined for k in ["cli", "command line", "argparse", "click", "terminal", "argv"]):
        return "cli"
    if any(k in combined for k in ["library", "package", "module", "sdk", "pip install"]):
        return "library"
    if any(k in combined for k in ["test", "pytest", "unittest", "jest", "spec"]):
        return "test"
    return "general"


class CoderAgent(BaseAgent):

    def __init__(self, memory=None) -> None:
        super().__init__(AgentType.CODER, memory)

    def _build_system_prompt(self) -> str:
        return """\
[PERSONA]
Your name is Kenji. Coding is a craft — every line deliberate, every function purposeful.
"Writing code that works is the start; writing code that is readable, testable,
and maintainable is the art."
You never ship half-finished work. It's either complete or it's not done.

[ROLE]
Write production-quality, COMPLETE, immediately runnable code.
ALL output must be in English (comments, variable names, docstrings, explanations).

[UNIVERSAL STANDARDS — apply to all task types]
1. COMPLETENESS   — NO pseudo-code, NO placeholders, NO "TODO: fill this in",
                    NO "// add your logic here", NO skeleton stubs. Every function must
                    have a full, working body. The output must run as-is.
2. LANGUAGE TAGS  — Always label code blocks: ```python, ```html, ```css, ```js, etc.
3. TECH RESPECT   — Honour every constraint in the spec exactly.
4. ERROR HANDLING — Use the idiomatic error handling of the language (try/except, Result<T>, etc.)
5. MULTIPLE FILES — Separate each file with ### filename.ext ### headers above its code block.
6. RUNNABILITY    — Deliver everything needed to run the project immediately.
7. DEPENDENCIES   — Always include requirements.txt or package.json if external packages are used.
8. SELF-CHECK     — Before finishing, ask: "Does this run perfectly right now?" If no → keep coding.

[WEB / UI TASKS — additional rules]
When building any website or web UI:
  a) NAVIGATION  — Fixed/sticky navbar with logo and nav links.
  b) HERO        — CSS gradient background (NOT placeholder images).
                   Example: background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  c) COLORS      — Define a CSS variable color scheme (--primary, --secondary, --accent, --bg, --text).
                   Use vibrant, contrasting colors. Never use #f0f0f0 or gray as primary palette.
  d) CARDS       — Gradient or colored backgrounds, hover effects (transform + shadow).
  e) TYPOGRAPHY  — Use Google Fonts CDN (Poppins or Inter). Set proper font-size hierarchy.
  f) SPACING     — Sections: at least 80px vertical padding. Cards: proper gap/margin.
  g) FOOTER      — Always include a full footer.
  h) RESPONSIVE  — @media queries for mobile (max-width: 768px).
  i) ANIMATIONS  — CSS transitions on hover, at least one keyframe animation.
  j) REAL CONTENT — Use real names, descriptions, data. Minimum 6+ items in galleries/listings.
  k) IMAGES      — ONLY use Unsplash CDN: https://images.unsplash.com/photo-{ID}?w=800&q=80&auto=format&fit=crop
                   NEVER use placeholder.com, picsum, or any placeholder service.

[API TASKS — additional rules]
When building REST APIs (Flask, FastAPI, Express, etc.):
  a) Include all endpoints fully implemented (not just stubs).
  b) Add request validation and proper HTTP status codes.
  c) Include Pydantic models or equivalent schema validation.
  d) Add error handlers for common cases (404, 422, 500).
  e) Include a README or docstring explaining how to run and use the API.
  f) Add at least basic authentication if the spec mentions users.

[CLI TASKS — additional rules]
When building command-line tools:
  a) Use argparse, click, or typer — fully configured with help text.
  b) Include --help output that is clear and complete.
  c) Handle all edge cases: missing files, wrong types, empty input.
  d) Add colored output if it improves UX (use colorama or rich).
  e) Include a usage example in comments.

[PYTHON SCRIPT / GENERAL TASKS]
When building scripts or utilities:
  a) Use type hints throughout.
  b) Docstrings on all public functions and classes.
  c) Proper __main__ guard if it's a script.
  d) Configuration via constants at the top or via argparse — never hardcoded buried values.
  e) Logging instead of bare print() for important events.

[CONTEXT]
Implement Aria's spec exactly. If information is missing, make a reasonable assumption
and state it explicitly in a comment. Never let a gap become a placeholder.
Respond entirely in English."""

    async def execute(self, task: Task, emit: Emitter = noop) -> AgentResult:
        task_type = _detect_task_type(task.description, task.context or "")
        console.print(
            f"\n  [bold green]💻 Kenji (Coder)[/bold green]: "
            f"'{task.description[:65]}{'…' if len(task.description) > 65 else ''}' [{task_type}]"
        )
        await emit(wrap("task.start", {
            "task_id":     task.id,
            "agent_type":  "coder",
            "description": task.description,
            "persona":     "Kenji",
        }))

        # ── Web araması (sadece kodlama/API görevlerinde değer katar) ─────────
        search_section = ""
        if task_type in ("api", "library", "general"):
            console.print("  [dim cyan]  Hızlı web araması...[/dim cyan]")
            search_query = f"{task.description[:100]} implementation example"
            search_results = await quick_search(search_query, max_results=3)
            if search_results:
                search_section = f"\n\n[CODE REFERENCES — use as guidance only, adapt to your spec]\n{search_results[:1500]}"

        # ── Görev tipine özel direktif ─────────────────────────────────────────
        type_directive = {
            "web":     "Build the complete website. Every section must look professional and polished.",
            "api":     "Build the complete API with all endpoints, validation, error handling, and a working entry point.",
            "cli":     "Build the complete CLI tool with full argument parsing, help text, and all functionality.",
            "library": "Build the complete library/module with all public API, docstrings, and usage examples.",
            "test":    "Write the complete test suite with all test categories covered.",
            "general": "Build the complete implementation. All functions must be fully implemented.",
        }.get(task_type, "Build the complete, production-ready implementation.")

        ctx = f"\n\n{task.context}" if task.context else ""
        prompt = f"""Task: {task.description}{ctx}{search_section}

{type_directive}

MANDATORY:
1. NO placeholders, stubs, or TODOs — every line must be real and working.
2. For multiple files: use ### filename.ext ### headers before each code block.
3. {
    "Use ONLY Unsplash URLs for images. Define CSS variables for colors. Include navbar, hero, cards, footer, animations."
    if task_type == "web" else
    "Include all endpoints with full implementations, validation, and error handling."
    if task_type == "api" else
    "Include all CLI arguments, help text, and complete feature implementations."
    if task_type == "cli" else
    "Include type hints, docstrings, and a working __main__ example."
}
4. After writing, mentally run the code: does it work immediately without any edits? If no → fix it.

Respond entirely in English."""

        console.print(
            f"  [dim cyan]  Prompt: {len(prompt):,} chars | Context: {len(task.context or ''):,} chars[/dim cyan]"
        )

        try:
            out = await self._generate(
                prompt, task_id=task.id, emit=emit,
                max_chars=20_000,  # Karmaşık görevlerde uzun kod gerekebilir
            )
            console.print(f"  [bold green]  ✓ Kenji tamamlandı — {len(out):,} karakter[/bold green]")
            return self._ok(task, out)
        except Exception as exc:
            console.print(f"  [bold red]  ✗ Kenji hata: {exc}[/bold red]")
            return self._fail(task, str(exc))
