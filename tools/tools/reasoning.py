from typing import Optional, Dict, Any, List
from fastmcp import FastMCP

def register_reasoning_tools(mcp: FastMCP, thinking_svc, diag_svc, project_root: str):
    @mcp.tool()
    async def sequentialthinking(
        thought: str,
        thought_number: int,
        total_thoughts: int,
        next_thought_needed: bool,
        is_revision: bool = False,
        revises_thought: Optional[int] = None,
        branch_from_thought: Optional[int] = None,
        branch_id: Optional[str] = None,
        needs_more_thoughts: bool = False,
        context: Optional[Dict[str, Any]] = None,
        available_tools: Optional[List[str]] = None,
        memory_keys: Optional[List[str]] = None,
    ) -> str:
        """
        A detailed tool for dynamic reasoning and mini-agent planning.
        This tool analyzes your thoughts, fetches auto-memory context, and suggests tools.
        adapt and evolve. Each thought can build on, question, or revise previous insights.

        When to use this tool:
        - Breaking down complex problems into manageable steps.
        - Planning and design with room for revision.
        - Analysis that might need course correction.
        - Problems where the full scope might not be clear initially.

        Key features:
        - Adjust total_thoughts up or down as you progress.
        - Revise previous thoughts using is_revision + revises_thought.
        - Branch into alternative approaches using branch_from_thought + branch_id.
        - Add more thoughts even after reaching what seemed like the end.

        Parameters:
        - thought: Your current thinking step (analysis, hypothesis, etc.).
        - thought_number: Current number in sequence.
        - total_thoughts: Estimated remaining thoughts needed.
        - next_thought_needed: True if more thinking is needed.
        - context: Optional dict containing current context (e.g. status_code, service names).
        - available_tools: Optional list of tool names (strings) you can use.
        - memory_keys: Optional list of keywords to auto-retrieve past facts.
        """
        err = await diag_svc.check_tool_dependency("sequentialthinking")
        if err: return err

        import json
        result = await thinking_svc.add_thought(
            thought=thought,
            thought_number=thought_number,
            total_thoughts=total_thoughts,
            next_thought_needed=next_thought_needed,
            is_revision=is_revision,
            revises_thought=revises_thought,
            branch_from_thought=branch_from_thought,
            branch_id=branch_id,
            needs_more_thoughts=needs_more_thoughts,
            context=context,
            memory_keys=memory_keys,
            available_tools=available_tools,
            project_root=project_root
        )
        return json.dumps(result, indent=2, ensure_ascii=False)
