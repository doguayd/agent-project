"""
Debugger Agent — Neo
====================
Language: English only (inter-agent communication).
Persona : Calm detective. Follows the trail from symptom to root cause.
Model   : qwen2.5-coder:14b (RTX 4090 GPU / CPU fallback)
"""

from __future__ import annotations

from rich.console import Console

from agents.base_agent import BaseAgent
from core.events import Emitter, noop, wrap
from core.models import AgentResult, AgentType, Task
from tools.web_search import quick_search

console = Console()


class DebuggerAgent(BaseAgent):

    def __init__(self, memory=None) -> None:
        super().__init__(AgentType.DEBUGGER, memory)

    def _build_system_prompt(self) -> str:
        return """\
[PERSONA]
Your name is Neo. A bug is a puzzle — you can't rest until it's solved.
You move from symptoms to root cause, step by step, never guessing.
"Don't assume. Prove it. Every bug is a cause-and-effect chain."

[ROLE]
Find the root cause, apply a minimal targeted fix, verify no regressions.
ALL output must be in English.

[METHODOLOGY]
1. 🔍 ANALYSE   — Examine error messages, stack traces, and code
2. 🎯 HYPOTHESISE — List possible causes (most likely first)
3. 🧪 VERIFY    — Mentally confirm each hypothesis
4. 🎯 ROOT CAUSE — Identify the actual problem (not the symptom)
5. 🔧 FIX       — Minimal, targeted correction (no side effects)
6. ✅ VALIDATE  — Confirm the fix doesn't introduce new issues

[OUTPUT FORMAT]
**ROOT CAUSE:** (one clear sentence)

**PROBLEMATIC CODE:**
```
... the broken lines with context ...
```

**EXPLANATION:** Why did this happen? (2-3 sentences)

**FIXED CODE:**
```
... complete working version ...
```

**PREVENTION:** How to avoid this class of bug in the future (if applicable)

Respond entirely in English."""

    async def execute(self, task: Task, emit: Emitter = noop) -> AgentResult:
        console.print(
            f"\n  [bold red]🐛 Neo (Debugger)[/bold red]: Tracing the bug..."
        )
        await emit(wrap("task.start", {
            "task_id":     task.id,
            "agent_type":  "debugger",
            "description": task.description,
            "persona":     "Neo",
        }))

        # Quick web search for known fix patterns (6-second max, no blocking)
        search_query = f"{task.description[:100]} fix solution"
        search_results = await quick_search(search_query, max_results=3)
        if search_results:
            console.print("  [dim]🌐 Neo: quick debug references injected[/dim]")
            search_section = f"""

[QUICK DEBUG REFERENCES — Known solutions from the web. Use as guidance.]
{search_results[:1500]}
"""
        else:
            search_section = ""

        ctx    = f"\nCode / Error detail:\n{task.context}" if task.context else ""
        prompt = f"""Debug this issue:

{task.description}{ctx}{search_section}

Follow your methodology. Find the root cause and provide the fixed code.
Respond entirely in English."""

        try:
            out = await self._generate(prompt, task_id=task.id, emit=emit)
            return self._ok(task, out)
        except Exception as exc:
            return self._fail(task, str(exc))
