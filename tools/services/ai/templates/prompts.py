import os
from typing import Dict, Any

class PromptTemplates:
    """Handles loading and formatting of system prompts."""
    
    def __init__(self, prompts_dir: str):
        self.prompts_dir = prompts_dir

    def get_prompt(self, name: str, variables: Dict[str, Any] = None) -> str:
        path = os.path.join(self.prompts_dir, f"{name}.md")
        if not os.path.exists(path): return f"Default prompt for {name}"
        
        with open(path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        if variables:
            for k, v in variables.items():
                template = template.replace(f"{{{{{k}}}}}", str(v))
        return template
