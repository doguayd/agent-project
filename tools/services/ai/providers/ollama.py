import requests
from typing import Dict, Any, Optional
from services.core.logger_service import setup_logger

class OllamaProvider:
    """Provider for Ollama local LLM service."""
    
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
        self.logger = setup_logger("AI.Ollama")
        self._ready = True # Simplified for testing

    async def is_ready(self) -> bool:
        return self._ready

    async def generate_response(self, prompt: str, context: str = "") -> str:
        """Generates a response using Ollama."""
        url = f"{self.host}/api/generate"
        payload = {"model": "qwen2.5-coder:7b", "prompt": prompt, "system": context, "stream": False}
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "No response from Ollama.")
        except Exception as e:
            self.logger.error(f"Ollama generation failed: {str(e)}")
            return f"Error: Ollama generation failed - {str(e)}"
