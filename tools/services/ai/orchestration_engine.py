import re
from typing import Dict, Any, List, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("OrchestrationEngine")

class OrchestrationEngine:
    """
    Lightweight rule-based planner engine.
    Analyzes thoughts to predict the next best tool and evaluates execution risk.
    Now optimized to use in-memory context instead of disk-based audit logs.
    """

    # Deterministic tools that are generally safe to execute automatically if confidence is very high
    DETERMINISTIC_TOOLS = {
        "kubectl_exec", "search_files", "read_file", "list_directory_with_sizes",
        "search_semantic_memory", "memory_retrieve_facts", "get_file_info", 
        "check_port", "system_info", "read_multiple_files",
        "directory_tree", "grep_search"
    }

    # High-risk tools that should NEVER auto-execute without explicit agent multi-step planning
    HIGH_RISK_TOOLS = {
        "write_file", "multi_replace_file_content", "apply_patch", "run_command", "send_command_input",
        "manage_background_job", "remote_ssh_command", "move_file", "create_directory"
    }

    def __init__(self):
        pass

    def analyze(self, thought: str, context: Dict[str, Any], available_tools: List[str], 
                memory_context: Optional[List[str]] = None, 
                recent_actions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Analyzes the thought and context to produce a structured decision and tool suggestion.
        recent_actions: List of last N tool suggestions from in-memory history.
        """
        thought_lower = thought.lower()
        context_str = str(context).lower()
        
        confidence = 0.5
        focus = "General analysis"
        complexity = "low"
        risk_level = "low"
        root_cause_hint = None
        suggested_tool = None
        suggested_args = {}
        warnings = []
        
        # 1. Intent & Focus Analysis based on keywords
        if any(w in thought_lower for w in ["error", "404", "500", "fail", "wrong", "hata"]):
            focus = "Debugging error state"
            if any(w in thought_lower for w in ["route", "gateway", "ingress", "path"]):
                root_cause_hint = "Routing mapping issue or unavailable upstream"
            elif any(w in thought_lower for w in ["database", "sql", "db", "connection"]):
                root_cause_hint = "Database connectivity or query failure"
                
        elif any(w in thought_lower for w in ["config", "env", "setup", "ayar"]):
            focus = "Configuration and environment analysis"
            
        elif any(w in thought_lower for w in ["log", "trace", "audit", "izleme"]):
            focus = "System inspection"
            
        elif any(w in thought_lower for w in ["search", "find", "where", "ara"]):
            focus = "Codebase exploration"
 
        # Boost confidence based on context richness
        if context and len(context) > 0:
            confidence += 0.1
            if "status_code" in context_str or "service" in context_str:
                confidence += 0.05
 
        # 2. Tool Suggestion Logic
        tool_score = {}
        for tool in available_tools:
            tool_score[tool] = 0
            
            # Simple scoring heuristics
            if tool in ["search_files", "search_semantic", "memory_search_semantic", "grep_search"] and focus == "Codebase exploration":
                tool_score[tool] += 3
            if tool in ["kubectl_exec", "remote_ssh_command", "run_command"] and (focus == "System inspection" or any(w in thought_lower for w in ["pod", "server", "docker"])):
                tool_score[tool] += 3
            if tool in ["read_file", "view_file"] and any(w in thought_lower for w in ["file", "read", "oku", "dosya"]):
                tool_score[tool] += 2
            if tool in ["multi_replace_file_content", "write_file", "apply_patch"] and any(w in thought_lower for w in ["change", "fix", "update", "güncelle", "yaz"]):
                tool_score[tool] += 2
                complexity = "medium"
            if tool in ["read_env_file", "write_env_key"] and any(w in thought_lower for w in ["env", "secret", "gizli"]):
                tool_score[tool] += 3
 
        # 3. Memory-Aware Correction & Contradiction Detection
        if memory_context:
            confidence += 0.1
            for fact in memory_context:
                fact_l = fact.lower()
                if any(w in thought_lower for w in ["edit", "update", "write", "fix", "düzelt"]):
                    if any(w in fact_l for w in ["read-only", "kısıtlı", "salt okunur", "readonly"]):
                        warnings.append(f"Memory Contradiction: Targeted resource might be restricted ({fact})")
                        confidence -= 0.3
                if "ssh" in thought_lower:
                    if any(w in fact_l for w in ["ssh disabled", "ssh kapalı", "no access"]):
                        warnings.append(f"Memory Contradiction: SSH access might be unavailable according to past logs.")
                        confidence -= 0.4
 
        # 4. In-Memory Loop Detection (Replacing Audit Logs)
        if recent_actions:
            if len(recent_actions) >= 2 and len(set(recent_actions)) == 1:
                # We are suggesting the same tool repeatedly
                focus = "Breaking tool suggestion loop"
                last_tool = recent_actions[0]
                if last_tool in tool_score:
                    tool_score[last_tool] -= 3
                    warnings.append(f"Loop Warning: {last_tool} was suggested repeatedly. Pivot to new approach.")
                    confidence -= 0.2
 
        # Select highest scoring tool
        best_tool = None
        if tool_score:
            sorted_tools = sorted(tool_score.items(), key=lambda item: item[1], reverse=True)
            if sorted_tools[0][1] > 0:
                best_tool = sorted_tools[0][0]
                confidence += 0.1
 
        # Build args hint
        if best_tool in ["search_files", "search_semantic", "memory_search_semantic", "grep_search"]:
            match = re.search(r"['\"](.*?)['\"]", thought)
            if match:
                suggested_args["query"] = match.group(1)
 
        # Risk Assessment
        if best_tool in self.HIGH_RISK_TOOLS:
            risk_level = "high"
        elif best_tool in ["multi_replace_file_content", "apply_patch", "run_command"]:
            risk_level = "medium"

        # Cap confidence
        confidence = min(round(confidence, 2), 0.95)
        
        # 5. Execution Rules
        execute_now = False
        if best_tool:
            is_deterministic = best_tool in self.DETERMINISTIC_TOOLS
            is_high_risk = best_tool in self.HIGH_RISK_TOOLS
            if confidence >= 0.90 and is_deterministic and not is_high_risk and not warnings:
                execute_now = True

        # Build response
        result = {
            "decision": {
                "current_focus": focus,
                "confidence": confidence,
                "complexity": complexity,
                "risk_level": risk_level
            },
            "next_action": "suggest_tool" if best_tool else "continue_thinking",
            "execute_now": execute_now
        }

        if warnings:
            result["decision"]["warnings"] = warnings
        if root_cause_hint:
            result["decision"]["potential_root_cause"] = root_cause_hint

        if best_tool:
            result["tool_suggestion"] = {
                "tool": best_tool,
                "args": suggested_args,
                "confidence": confidence
            }
            if execute_now:
                args_hint = ", ".join([f"{k}='{v}'" for k,v in suggested_args.items()])
                result["command_hint"] = f"{best_tool}({args_hint})"

        return result
