import json
from typing import List, Optional, Dict, Any
from fastmcp import FastMCP


def register_task_tools(mcp: FastMCP, task_svc, planner_svc, diag_svc):

    @mcp.tool()
    async def create_plan(
        goal: str,
        project_root: str,
        execution_plan: List[Dict[str, Any]],
        problem_analysis: Optional[Dict[str, Any]] = None,
        best_practices: Optional[List[str]] = None,
        risk_assessment: Optional[List[str]] = None,
        context: Optional[str] = None,
        constraints: Optional[List[str]] = None,
    ) -> str:
        """
        Analyze a problem and produce a structured execution plan before making changes.

        USAGE INSTRUCTIONS FOR THE CALLING MODEL:
        - Before calling this tool, reason through the problem thoroughly.
        - YOU are responsible for producing the plan content — no external AI is used.
        - Populate ALL fields based on your own analysis.

        Parameters:
        - goal: What the user ultimately wants to achieve.
        - context: Relevant technical context (codebase, environment, constraints).
        - constraints: Hard limitations or requirements (e.g. "do not modify auth logic").
        - problem_analysis: {
            "core_problem": "Short explanation of the real underlying issue",
            "critical_points": ["risk", "edge case", "dependency impact"]
          }
        - best_practices: Relevant engineering or architecture guidelines.
        - risk_assessment: Possible breaking changes or performance impacts.
        - execution_plan: [
            {"step": 1, "action": "...", "expected_result": "..."},
            ...
          ]

        Returns: A task_id string you can use with task_mark_step to track progress.
        """
        err = await diag_svc.check_tool_dependency("create_plan")
        if err: return err

        try:
            # Validate + structure via PlannerService (no LLM, pure logic)
            ok, msg, structured = planner_svc.structure_plan(
                goal=goal,
                execution_plan=execution_plan,
                problem_analysis=problem_analysis,
                best_practices=best_practices,
                risk_assessment=risk_assessment,
                context=context,
                constraints=constraints,
            )

            if not ok:
                return f"PLAN VALIDATION ERROR: {msg}"

            # Persist via TaskService
            task_id = task_svc.create_plan(
                title=goal,
                execution_plan=structured["execution_plan"],
                problem_analysis=structured["problem_analysis"],
                best_practices=structured["best_practices"],
                risk_assessment=structured["risk_assessment"],
                project_root=project_root,
            )

            summary = {
                "task_id": task_id,
                "goal": structured["goal"],
                "steps": len(structured["execution_plan"]),
                "risks": len(structured["risk_assessment"]),
                "message": "Plan created. Use task_mark_step(task_id, step, status) to track progress.",
            }
            return json.dumps(summary, indent=2, ensure_ascii=False)

        except Exception as e:
            return f"ERROR: {str(e)}"

    @mcp.tool()
    async def task_mark_step(task_id: str, step_index: int, status: str, project_root: str) -> str:
        """
        Mark a specific step of a plan as 'todo', 'in_progress', or 'done'.
        Call this after completing each step so progress is tracked.
        """
        err = await diag_svc.check_tool_dependency("task_mark_step")
        if err: return err

        try:
            return task_svc.mark_step(task_id, step_index, status, project_root=project_root)
        except Exception as e:
            return str(e)

    @mcp.tool()
    async def task_get_active(project_root: str) -> str:
        """Retrieve all active, non-completed plans and their steps."""
        err = await diag_svc.check_tool_dependency("task_get_active")
        if err: return err

        try:
            active = task_svc.get_active_tasks(project_root=project_root)
            return json.dumps(active, indent=2, ensure_ascii=False) if active else "No active tasks. You are free!"
        except Exception as e:
            return str(e)
