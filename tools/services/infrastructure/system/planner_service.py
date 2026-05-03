import json
from typing import Optional, List, Dict, Any
from services.core.logger_service import setup_logger

logger = setup_logger("PlannerService")


class PlannerService:
    """
    Pure plan structurer and validator.
    
    The main LLM (the model calling this tool) is responsible for producing
    the plan content. This service only validates, normalises, and prepares
    the structure before it is persisted by TaskService.
    No external LLM or Ollama dependency.
    """

    # ------------------------------------------------------------------ #
    #  Validation helpers                                                  #
    # ------------------------------------------------------------------ #

    def validate_execution_plan(self, execution_plan: List[Dict[str, Any]]) -> tuple[bool, str]:
        """Ensure every step has the required keys."""
        if not execution_plan:
            return False, "execution_plan must contain at least one step."

        required_keys = {"step", "action", "expected_result"}
        for i, step in enumerate(execution_plan):
            missing = required_keys - step.keys()
            if missing:
                return False, f"Step {i + 1} is missing required keys: {missing}"
            if not str(step.get("action", "")).strip():
                return False, f"Step {i + 1} 'action' cannot be empty."

        return True, "OK"

    def validate_problem_analysis(self, problem_analysis: Optional[Dict]) -> tuple[bool, str]:
        """Ensure problem_analysis has the expected structure."""
        if problem_analysis is None:
            return True, "OK (optional, skipped)"

        if "core_problem" not in problem_analysis:
            return False, "problem_analysis must contain 'core_problem'."
        if not str(problem_analysis.get("core_problem", "")).strip():
            return False, "problem_analysis.core_problem cannot be empty."

        return True, "OK"

    # ------------------------------------------------------------------ #
    #  Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def structure_plan(
        self,
        goal: str,
        execution_plan: List[Dict[str, Any]],
        problem_analysis: Optional[Dict[str, Any]] = None,
        best_practices: Optional[List[str]] = None,
        risk_assessment: Optional[List[str]] = None,
        context: Optional[str] = None,
        constraints: Optional[List[str]] = None,
    ) -> tuple[bool, str, Dict[str, Any]]:
        """
        Validate and normalise a plan produced by the main model.

        Returns:
            (success: bool, message: str, structured_plan: dict)
        """
        # --- Validate goal ---
        if not goal or not goal.strip():
            return False, "goal cannot be empty.", {}

        # --- Validate execution plan ---
        ok, msg = self.validate_execution_plan(execution_plan)
        if not ok:
            return False, msg, {}

        # --- Validate problem analysis ---
        ok, msg = self.validate_problem_analysis(problem_analysis)
        if not ok:
            return False, msg, {}

        # --- Normalise step indices (ensure sequential) ---
        normalised_steps = []
        for i, step in enumerate(execution_plan):
            normalised_steps.append({
                "step": i + 1,
                "action": str(step["action"]).strip(),
                "expected_result": str(step.get("expected_result", "")).strip(),
                "status": "todo",
            })

        structured = {
            "goal": goal.strip(),
            "context": context or "",
            "constraints": constraints or [],
            "problem_analysis": problem_analysis or {},
            "best_practices": best_practices or [],
            "risk_assessment": risk_assessment or [],
            "execution_plan": normalised_steps,
        }

        logger.info(f"Plan structured successfully: '{goal[:60]}...' ({len(normalised_steps)} steps)")
        return True, "Plan validated and structured successfully.", structured
