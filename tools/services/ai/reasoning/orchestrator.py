from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("AI.Orchestrator")

class Orchestrator:
    """Intelligent recovery and tool selection engine."""
    
    @staticmethod
    def analyze_failure(tool_name: str, error: str) -> str:
        """Suggests a recovery action based on the error type."""
        logger.warning(f"Failure detected in {tool_name}: {error}")
        if "not found" in error.lower(): return "Try searching for the file first."
        if "permission" in error.lower(): return "Check if the path is restricted or requires elevation."
        return "Try an alternative tool or check the documentation."

    @staticmethod
    def suggest_next_tool(task: str, available_tools: List[str]) -> Optional[str]:
        """Simple heuristic for next tool prediction."""
        if "search" in task.lower():
            for t in ["search_semantic_memory", "grep_search"]:
                if t in available_tools: return t
        return None
