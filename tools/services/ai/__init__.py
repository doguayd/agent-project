from typing import List, Dict, Any, Optional
from .providers.llama import LlamaProvider
from .providers.ollama import OllamaProvider
from .reasoning.orchestrator import Orchestrator
from .reasoning.thinking import ThinkingLoop
from .templates.prompts import PromptTemplates

class AIService:
    """Consolidated service for AI operations."""
    
    def __init__(self, model_path: str, prompts_dir: str):
        self.llama = LlamaProvider(model_path)
        self.ollama = OllamaProvider()
        self.orchestrator = Orchestrator()
        self.thinking = ThinkingLoop()
        self.prompts = PromptTemplates(prompts_dir)

    def initialize(self):
        self.llama.initialize()

    async def get_embeddings(self, text: str):
        return await self.llama.get_embeddings(text)

    @property
    def is_ready(self) -> bool:
        return self.llama.is_ready
