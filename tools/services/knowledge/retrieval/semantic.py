from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("Knowledge.Semantic")

class SemanticEngine:
    """Handles vector embeddings and anlamsal (semantic) search."""
    
    def __init__(self, llama_svc: Any, store: Any):
        self.llama_svc = llama_svc
        self.store = store

    async def index(self, text: str, metadata: Dict[str, Any], doc_id: str):
        if not self.llama_svc or not self.llama_svc.is_ready:
            logger.error("Embedding engine not ready.")
            return False
        
        embedding = await self.llama_svc.get_embeddings(text)
        self.store.add_vector(doc_id, text, metadata, embedding)
        return True

    async def search(self, query: str, n: int = 5) -> List[Dict]:
        if not self.llama_svc or not self.llama_svc.is_ready:
            return []
        
        query_vec = await self.llama_svc.get_embeddings(query)
        return self.store.query_vector(query_vec, n)

    async def delete_by_path(self, path: str):
        """Removes all vectors associated with a specific file path."""
        self.store.delete_vector_by_id(path)

    def get_indexed_paths(self) -> List[str]:
        """Returns a list of all file paths currently in the semantic memory."""
        return self.store.get_all_ids()
