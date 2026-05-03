from typing import List, Dict, Any, Optional

class ThinkingLoop:
    """Manages reasoning history and prevents infinite tool loops."""
    
    def __init__(self, max_history: int = 20):
        self.history = []
        self.max_history = max_history

    def record_step(self, tool: str, result_summary: str):
        self.history.append({"tool": tool, "result": result_summary})
        if len(self.history) > self.max_history:
            self.history.pop(0)

    async def add_thought(self, **kwargs) -> Dict[str, Any]:
        """
        Processes and stores a dynamic reasoning thought.
        Returns a structured response for the sequentialthinking tool.
        """
        thought_data = {
            "thought": kwargs.get("thought"),
            "thought_number": kwargs.get("thought_number"),
            "total_thoughts": kwargs.get("total_thoughts"),
            "next_thought_needed": kwargs.get("next_thought_needed")
        }
        
        # Add to history for loop detection / tracking
        self.record_step("sequentialthinking", f"Thought #{kwargs.get('thought_number')}")
        
        # Return the same data + any additional metadata
        return {
            "status": "success",
            "data": thought_data,
            "loop_detected": self.detect_loop()
        }

    def detect_loop(self) -> bool:
        if len(self.history) < 3: return False
        # Simple recent repetition check
        last_three = [h["tool"] for h in self.history[-3:]]
        return len(set(last_three)) == 1
