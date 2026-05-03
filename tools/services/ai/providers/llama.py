import os
import asyncio
import requests
from pathlib import Path
from tqdm import tqdm
from llama_cpp import Llama
from services.core.logger_service import setup_logger

logger = setup_logger("AI.Llama")

class LlamaProvider:
    """Handles local GGUF models and embedding generation."""
    
    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.client = None
        self._ready = False

    async def is_ready(self) -> bool:
        return self._ready

    def ensure_model(self):
        if self.model_path.exists():
            logger.info(f"Model exists: {self.model_path}")
            return
        
        logger.info(f"Downloading model to {self.model_path}...")
        response = requests.get(self.DEFAULT_MODEL_URL, stream=True)
        with open(self.model_path, "wb") as f:
            for data in response.iter_content(1024*1024): f.write(data)
        logger.info("Download complete.")

    def initialize(self):
        try:
            self.ensure_model()
            # If the model is corrupt or invalid, this is where it crashes usually.
            # We wrap it to allow the server to start anyway.
            self.client = Llama(model_path=str(self.model_path), embedding=True, verbose=False, n_ctx=384)
            self._ready = True
            logger.info("LlamaProvider initialized successfully.")
        except Exception as e:
            self._ready = False
            logger.error(f"Llama initialization deferred or failed: {e}")
            # Do NOT raise, just stay un-ready.

    async def get_embeddings(self, text: str):
        if not self.client: 
            self.initialize()
        
        if not self._ready:
            return [0.0] * 384 # Fallback zero vector if failed
            
        try:
            # Offload heavy CPU work to a thread
            res = await asyncio.to_thread(self.client.create_embedding, text)
            return res['data'][0]['embedding']
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return [0.0] * 384
