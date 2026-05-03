"""
Tester Agent — Zara
===================
Language: English only (inter-agent communication).
Persona : Methodical, sceptical, tries to break everything.
Model   : qwen2.5-coder:14b (RTX 4090 GPU / CPU fallback)
"""

from __future__ import annotations

import re
from rich.console import Console

from agents.base_agent import BaseAgent
from core.events import Emitter, noop, wrap
from core.models import AgentResult, AgentType, Task

console = Console()


def _extract_test_targets(code: str) -> str:
    """
    Koddan test yazılabilecek hedefleri çıkar:
    - Python: def/class isimlerini bul
    - JS/TS: function/class/export isimlerini bul
    - API: endpoint route'larını bul
    """
    targets = []

    # Python functions & classes
    for m in re.finditer(r'^(?:def|class|async def)\s+(\w+)', code, re.MULTILINE):
        name = m.group(1)
        if not name.startswith('_'):
            targets.append(f"Python: {m.group(0).strip()}")

    # JS/TS functions & exports
    for m in re.finditer(r'(?:export\s+)?(?:function|const|class)\s+(\w+)', code):
        targets.append(f"JS/TS: {m.group(0)[:60]}")

    # API endpoints (Flask/FastAPI/Express)
    for m in re.finditer(r'@(?:app|router)\.(?:get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]', code):
        targets.append(f"API endpoint: {m.group(1)}")

    # Deduplicate and limit
    seen = set()
    unique = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return "\n".join(unique[:30]) if unique else ""


class TesterAgent(BaseAgent):

    def __init__(self, memory=None) -> None:
        super().__init__(AgentType.TESTER, memory)

    def _build_system_prompt(self) -> str:
        return """\
[PERSONA]
Your name is Zara. Breaking things is your art form.
"A system isn't tested to be safe — it's tested so it can't break."
While devs say "that will never happen", you test exactly that.

[ROLE]
Write comprehensive, immediately runnable test suites for the given code.
ALL output must be in English.

[COVERAGE — every test file must include all applicable categories]
1. HAPPY PATH      — Normal, expected usage with valid inputs
2. EDGE CASES      — Boundary values (0, -1, maxint, empty string, None, [], {})
3. ERROR SCENARIOS — Invalid input, missing required fields, network failure, timeout
4. INTEGRATION     — Multiple components working together (if applicable)
5. CONCURRENCY     — Thread/async safety where applicable

[STANDARDS]
- Test names must describe the scenario:
    test_user_registration_with_duplicate_email_returns_409
    test_search_with_empty_query_returns_empty_list
- Python  → pytest + fixtures + @pytest.mark.parametrize where beneficial
- JS/TS   → jest or vitest + describe/it/expect blocks
- API     → Use requests or httpx TestClient + all HTTP methods + all status codes
- Each test is fully independent (proper setup/teardown, no shared state)
- Mock/patch ALL external dependencies (DB calls, HTTP requests, file I/O)
- Assert with descriptive messages: assert result == expected, f"Got {result}"

[OUTPUT]
1. Complete, runnable test file with all imports at the top
2. Tests grouped by feature/module using describe blocks or pytest classes
3. A conftest.py if fixtures are needed (as a separate ### conftest.py ### file)
4. End with a summary comment: total test count and coverage areas

Respond entirely in English."""

    async def execute(self, task: Task, emit: Emitter = noop) -> AgentResult:
        console.print(
            f"\n  [bold cyan]🧪 Zara (Tester)[/bold cyan]: Analyzing code and writing tests..."
        )
        await emit(wrap("task.start", {
            "task_id":     task.id,
            "agent_type":  "tester",
            "description": task.description,
            "persona":     "Zara",
        }))

        code = task.context if task.context else task.description

        # Koddan test hedeflerini otomatik çıkar
        targets = _extract_test_targets(code)
        targets_section = ""
        if targets:
            console.print(f"  [dim]🎯 Zara: {targets.count(chr(10))+1} test hedefi tespit edildi[/dim]")
            targets_section = f"\n\n[AUTO-DETECTED TEST TARGETS — ensure full coverage of these]\n{targets}"

        prompt = f"""Write a comprehensive test suite for the following code.

Task: {task.description}{targets_section}

Code to test:
{code}

Requirements:
1. Cover ALL detected test targets — every function, class, and API endpoint.
2. Write RUNNABLE tests — all imports must be correct, all fixtures must exist.
3. Include: happy path, edge cases (empty/None/boundary), and error scenarios.
4. Mock ALL external dependencies (database, HTTP calls, file system).
5. For API tests: test every endpoint with valid input, invalid input, and auth failures.
6. Use descriptive test names that document the expected behaviour.
7. Separate multiple test files with ### filename.ext ### headers.

Respond entirely in English."""

        try:
            out = await self._generate(
                prompt, task_id=task.id, emit=emit,
                max_chars=16_000,
            )
            return self._ok(task, out)
        except Exception as exc:
            return self._fail(task, str(exc))
