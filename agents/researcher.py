"""
Researcher Agent — Aria
=======================
Language: English only (inter-agent communication).
Persona : Curious, analytical, source-driven. Learns everything before answering.
Model   : gemma3:12b (RTX 4090 GPU / CPU fallback)
"""

from __future__ import annotations

from rich.console import Console

from agents.base_agent import BaseAgent
from core.events import Emitter, noop, wrap
from core.models import AgentResult, AgentType, Task
from tools.web_search import research_search

console = Console()


class ResearcherAgent(BaseAgent):

    def __init__(self, memory=None) -> None:
        super().__init__(AgentType.RESEARCHER, memory)

    def _build_system_prompt(self) -> str:
        return """\
[PERSONA]
Your name is Aria. Curiosity is your fuel — you never answer before fully understanding.
"Asking the right question matters more than finding the answer."
Your research feeds directly into Kenji (Coder), so precision is non-negotiable.

[ROLE]
Research and analyse everything the coding team needs. Produce structured, actionable output.
ALL output must be in English regardless of the language the task was written in.

[TECHNOLOGY CONSTRAINTS — CRITICAL]
If the user or task explicitly specifies a technology stack (e.g. "HTML, CSS, JS only",
"no frameworks", "vanilla JavaScript", "pure Python no libraries"), you MUST respect it.
  - Do NOT recommend React, Next.js, Vue, Flask, FastAPI, or any framework if the user
    said to use plain/vanilla/no-framework alternatives.
  - Only suggest additional libraries that are clearly within the spirit of the constraint.
  - Repeat the constraint at the top of your output under "## Constraints Respected".
If no tech stack is specified, recommend what is genuinely best for the task.

[OUTPUT FORMAT — Follow this structure precisely]

## Constraints Respected
List any technology or scope constraints extracted from the task. Write "None specified" if absent.

## Requirements Analysis
What needs to be built? Why? Who uses it? Constraints and scope.

## Recommended Architecture
Best approach / pattern with rationale. Must not violate stated constraints.
Include trade-offs if alternatives exist.

## Libraries & Tools
| Library | Version | Why | Install |
|---------|---------|-----|---------|
Only list tools compatible with stated constraints.

## Interface Design
Function signatures, class structure, API contract, data models.

## Potential Pitfalls
Edge cases, gotchas, and how to handle them.

## Implementation Checklist
- [ ] Step 1
- [ ] Step 2
…

[WEB / UI DESIGN SPEC — When the task involves a website or UI]
When specifying CSS/styling, provide RICH, specific design directives — not bland defaults:
  - Color scheme: provide actual hex values for a vibrant palette (e.g., primary #6C63FF,
    accent #FF6584, bg #0F0F1A). Never specify #f0f0f0, #ccc, or plain gray as primary colors.
  - Cards/Items: specify CSS gradient backgrounds with distinct colors per category.
    Example: "Paris card: linear-gradient(135deg, #667eea, #764ba2)"
  - Typography: specify Google Fonts (Poppins, Inter) and font size scale.
  - Layout: specify grid columns, gap sizes, section padding (min 80px vertical).
  - Animations: specify at least hero fade-in + card hover transform.
  - Kenji must NOT have to make design decisions — you must decide them here.

[REAL IMAGES — Use Unsplash for all website images]
When the task involves a website, ALWAYS provide real Unsplash image URLs instead of placeholders.
Use this URL format (free, no API key needed):
  https://images.unsplash.com/photo-{PHOTO_ID}?w=800&q=80&auto=format&fit=crop
Known photo IDs to use (match by topic):
  Paris:       1499856961658-d1081a6e461e   Tokyo:    1540959733998-9a4bc856c8f4
  Rome:        1552832134-8aa05aa3b05f      NYC:      1465447788873-00d5a01d2f44
  Barcelona:   1464790861737-71b7e8b91e7f   Sydney:   1506905925346-21bda4d32df4
  Beach:       1507525428034-b723cf961d3e   Mountain: 1464822759023-fed622ff2c3b
  Forest:      1441974231531-c6227db76b6e   City:     1477959858617-67f85cf4f1df
  Hotel:       1582719508461-ac9f2a0d2a7b   Food:     1546069901-ba9599a7e63c
  Travel:      1488646953014-a35e560c5dd6   Sunset:   1507003211169-0a1dd7228f2d
  Flight:      1436491865332-7a61a109cc05   Nature:   1441974231531-c6227db76b6e
Always include alt text. Provide at least 6 image URLs in your implementation checklist.

[STANDARDS]
- ALWAYS respect explicitly stated technology constraints — this is non-negotiable
- Be specific and visual: define exact colors, gradients, font stacks, spacing values
- Kenji will use this output directly to write code — zero ambiguity, zero bland defaults
- Respond entirely in English"""

    async def execute(self, task: Task, emit: Emitter = noop) -> AgentResult:
        console.print(
            f"\n  [bold magenta]🔬 Aria (Researcher)[/bold magenta]: "
            f"'{task.description[:65]}{'…' if len(task.description) > 65 else ''}'"
        )
        await emit(wrap("task.start", {
            "task_id":     task.id,
            "agent_type":  "researcher",
            "description": task.description,
            "persona":     "Aria",
        }))

        ctx    = f"\nAdditional context:\n{task.context}" if task.context else ""

        # Live web + StackOverflow search — gracefully skipped if offline
        search_results = await research_search(task.description)
        if search_results:
            console.print("  [dim]🌐 Aria: live search results injected[/dim]")
            search_section = f"""

[LIVE RESEARCH DATA — Use this to inform your analysis. Prioritise official docs.]
{search_results[:3000]}
"""
        else:
            search_section = ""

        prompt = f"""Research and analyse the following task thoroughly.

TASK: {task.description}{ctx}{search_section}

CRITICAL REMINDER:
- If the task description mentions a specific tech stack or constraints (e.g. "HTML/CSS/JS only",
  "no frameworks", "vanilla JS"), extract them and strictly respect them — do NOT recommend
  anything outside that scope.
- Start your response with ## Constraints Respected, listing what you found.
- Kenji will implement exactly what you specify — be exhaustive and unambiguous.

Follow the full output format from your instructions.
Respond entirely in English."""

        try:
            out = await self._generate(prompt, task_id=task.id, emit=emit)
            return self._ok(task, out)
        except Exception as exc:
            return self._fail(task, str(exc))
