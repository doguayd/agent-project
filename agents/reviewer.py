"""
Reviewer Agent — Rex
====================
Language: English only (inter-agent communication).
Persona : Critical, zero-tolerance, but constructive. No mediocrity passes.
Model   : qwen2.5-coder:14b (RTX 4090 GPU / CPU fallback)
"""

from __future__ import annotations

import re
from rich.console import Console

from agents.base_agent import BaseAgent
from core.events import Emitter, noop, wrap
from core.models import AgentResult, AgentType, Task
from tools.code_validator import validate_agent_output

console = Console()


def _check_completeness(code: str) -> list[str]:
    """
    Kodun tamamlanmamış işaretlerini tespit et.
    Returns list of completeness issues found.
    """
    issues = []
    lines = code.splitlines()
    todo_patterns = [
        r'\bTODO\b', r'\bFIXME\b', r'\bHACK\b', r'\bXXX\b',
        r'pass\s*#.*implement', r'raise NotImplementedError',
        r'#\s*add\s+your\s+(logic|code|implementation)',
        r'//\s*TODO', r'/\*\s*TODO',
        r'\.\.\.\s*#.*implement',
        r'placeholder', r'coming soon', r'lorem ipsum',
    ]
    for i, line in enumerate(lines, 1):
        for pat in todo_patterns:
            if re.search(pat, line, re.IGNORECASE):
                issues.append(f"line {i}: {line.strip()[:80]}")
                break
    return issues


class ReviewerAgent(BaseAgent):

    def __init__(self, memory=None) -> None:
        super().__init__(AgentType.REVIEWER, memory)

    def _build_system_prompt(self) -> str:
        return """\
[PERSONA]
Your name is Rex. You've seen every class of bug, security hole, and architectural mistake.
You're tough but fair — finding issues makes the code stronger, not weaker.
"I don't criticise; I give engineering feedback."

[ROLE]
Review code against the checklist below. Produce a structured, actionable report.
ALL output must be in English.

[SEVERITY LEVELS]
🔴 CRITICAL — Security vulnerability, data loss risk, crash on normal usage
🟠 MAJOR    — Incorrect behaviour, wrong algorithm, broken feature, incomplete implementation
🟡 MINOR    — Performance issue, readability problem, best-practice violation
🟢 SUGGEST  — Optional improvement or alternative approach

[CHECKLIST]
✅ COMPLETENESS  — No TODO, stub, placeholder, or unimplemented function?
                   Any "pass", "raise NotImplementedError", or empty bodies?
✅ CORRECTNESS   — Does it do exactly what the task requires?
🔒 SECURITY      — SQL injection, XSS, path traversal, hardcoded secrets, unvalidated input?
⚡ PERFORMANCE   — N+1 queries, unnecessary loops, large memory allocations?
📖 READABILITY   — Naming, structure, comment quality?
🛡 ERROR HANDLING — Edge cases, timeouts, empty/invalid inputs handled?
📐 BEST PRACTICES — Language/framework conventions followed?
🎨 UI QUALITY     — (for web tasks) Real content, proper CSS, no gray/placeholder boxes?

[VERDICT RULES]
APPROVED        — All features complete, no CRITICAL or MAJOR issues, code runs as-is
CHANGES_REQUIRED — Has MAJOR issues, or any placeholder/stub/TODO that blocks functionality
REJECTED        — CRITICAL security/data issues, or code is fundamentally broken

[OUTPUT FORMAT — strict]
VERDICT: APPROVED | CHANGES_REQUIRED | REJECTED

ISSUES:
  🔴 [CRITICAL] line X: Description + specific fix required
  🟠 [MAJOR]    line Y: Description + specific fix required
  🟡 [MINOR]    line Z: Description
  🟢 [SUGGEST]  Optional: Description

FIXED CODE:
(Provide ONLY the specific changed sections with 3-5 lines of surrounding context.
 Do NOT rewrite the entire codebase — only what needs fixing.)

SUMMARY: (2-3 sentences: what was built, what issues exist, what's needed next)

Respond entirely in English."""

    async def execute(self, task: Task, emit: Emitter = noop) -> AgentResult:
        console.print(
            f"\n  [bold yellow]🔍 Rex (Reviewer)[/bold yellow]: Reviewing code..."
        )
        await emit(wrap("task.start", {
            "task_id":     task.id,
            "agent_type":  "reviewer",
            "description": task.description,
            "persona":     "Rex",
        }))

        code = task.context if task.context else task.description

        # ── Otomatik tamamlanmamışlık tespiti ─────────────────────────────────
        completeness_issues = _check_completeness(code)
        if completeness_issues:
            console.print(
                f"  [yellow]⚠ Rex: {len(completeness_issues)} eksiklik tespit edildi (TODO/stub/placeholder)[/yellow]"
            )
            completeness_section = (
                "\n\n[AUTOMATED COMPLETENESS SCAN — These issues were auto-detected before your review]\n"
                + "\n".join(f"  ⚠ {issue}" for issue in completeness_issues[:20])
                + "\nThese MUST be listed as 🟠 MAJOR or 🔴 CRITICAL issues in your report.\n"
            )
        else:
            completeness_section = ""

        # ── Sözdizim doğrulama ─────────────────────────────────────────────────
        syntax_report = validate_agent_output(code)
        if syntax_report:
            has_errors = "❌" in syntax_report
            console.print(f"  [dim]{'🔴' if has_errors else '🟢'} Rex: {syntax_report.splitlines()[0]}[/dim]")
            syntax_section = f"\n\n[SYNTAX VALIDATION RESULTS]\n{syntax_report}"
        else:
            syntax_section = ""

        prompt = f"""Review this code thoroughly and produce a detailed report.

Task requirements: {task.description}

Code to review:
{code}{completeness_section}{syntax_section}

Apply the full checklist. Be specific with line numbers and fixes.
VERDICT must be CHANGES_REQUIRED if ANY placeholder, stub, TODO, or incomplete function exists.
Respond entirely in English."""

        try:
            out = await self._generate(
                prompt, task_id=task.id, emit=emit,
                max_chars=10_000,
            )
            return self._ok(task, out)
        except Exception as exc:
            return self._fail(task, str(exc))
