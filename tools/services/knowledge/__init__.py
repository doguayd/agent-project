import os
from typing import List, Dict, Any, Optional
from .storage.sqlite import SQLiteStore
from .repository.facts import FactRepository
from .retrieval.semantic import SemanticEngine
from .retrieval.hybrid import HybridResolver
from .retrieval.indexer import WorkspaceIndexer
from resources.config.settings import resolve_paths, resolve_best_project_context, save_to_registry, get_project_id

class KnowledgeBaseService:
    """Consolidated service for memory and knowledge management - Multi-Project Aware."""
    
    def __init__(self, local_dir: str, global_dir: str, llama_svc: Optional[Any] = None):
        self.default_local_dir = local_dir
        self.global_dir = global_dir
        self.llama_svc = llama_svc
        
        # Context Cache: {project_id: {store, facts, semantic, indexer}}
        self.contexts = {}
        self.resolver = HybridResolver()
        self.ignore_svc = None # Bridged later
        self.doc_svc = None    # Bridged later

    def _get_context(self, project_root: str) -> Dict[str, Any]:
        """Resolves the correct project context (store, facts, semantic)."""
        # 1. Hiyerarşik olarak en iyi eşleşen projeyi bul
        best_match = resolve_best_project_context(project_root)
        
        if best_match:
            project_id = best_match["id"]
            matched_root = best_match["path"]
        else:
            # Yeni proje olarak kaydet
            project_id = get_project_id(project_root)
            matched_root = project_root
            save_to_registry(project_root, project_id)

        if project_id in self.contexts:
            return self.contexts[project_id]

        # Context oluştur (Lazy initialization)
        paths = resolve_paths(matched_root)
        mem_dir = paths["local_memory"]
        os.makedirs(mem_dir, exist_ok=True)
        
        db_path = os.path.join(mem_dir, "local_memory.db")
        store = SQLiteStore(db_path)
        facts = FactRepository(db_path)
        semantic = SemanticEngine(self.llama_svc, store)
        
        ctx = {
            "store": store,
            "facts": facts,
            "semantic": semantic,
            "indexer": WorkspaceIndexer(self, self.ignore_svc, self.doc_svc) if self.ignore_svc else None,
            "project_id": project_id,
            "root": matched_root
        }
        self.contexts[project_id] = ctx
        return ctx

    async def store_fact(self, fact: str, project_root: str, entity: str = None, category: str = "general"):
        ctx = self._get_context(project_root)
        fact_id = ctx["facts"].add(fact, entity, category)
        # Auto-index for semantic search
        await ctx["semantic"].index(fact, {"type": "fact", "category": category}, f"fact_{fact_id}")
        return f"Fact stored in [{ctx['project_id']}] and indexed (ID: fact_{fact_id})"

    async def search(self, query: str, project_root: str, keyword_hits: List[Dict] = None, n: int = 5) -> List[Dict]:
        ctx = self._get_context(project_root)
        semantic_hits = await ctx["semantic"].search(query, n=n)
        return self.resolver.resolve(query, keyword_hits or [], semantic_hits, n=n)

    def set_indexer(self, ignore_svc: Any, doc_svc: Any):
        self.ignore_svc = ignore_svc
        self.doc_svc = doc_svc

    async def index_workspace(self, project_root: str):
        ctx = self._get_context(project_root)
        if not ctx["indexer"]:
            # Re-bridge if missing
            ctx["indexer"] = WorkspaceIndexer(self, self.ignore_svc, self.doc_svc)
            
        return await ctx["indexer"].index_workspace(project_root)

    def get_semantic_engine(self, project_root: str):
        """Helper for indexer to get the correct engine."""
        return self._get_context(project_root)["semantic"]
