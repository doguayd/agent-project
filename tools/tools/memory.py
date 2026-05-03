import json
from typing import Optional, Any
from fastmcp import FastMCP

def register_memory_tools(mcp: FastMCP, memory_svc, task_svc, doc_svc, PROJECT_ROOT, logger, diag_svc, ignore_svc, file_svc, async_task_svc=None):
    
    # Bridge dependencies to the memory service
    memory_svc.set_indexer(ignore_svc, doc_svc)
    
    @mcp.tool()
    async def memory_store_fact(fact: str, project_root: str, entity: Optional[str] = None, category: Optional[str] = "general") -> str:
        """Stores a durable fact in project memory."""
        return await memory_svc.store_fact(fact, project_root, entity, category)

    @mcp.tool()
    async def memory_retrieve_facts(project_root: str, query: Optional[str] = None, category: Optional[str] = None) -> str:
        """Retrieves stored project facts."""
        ctx = memory_svc._get_context(project_root)
        facts = ctx["facts"].list(query, category)
        return json.dumps(facts, indent=2)

    @mcp.tool()
    async def memory_index_workspace(project_root: str) -> str:
        """
        Indexes the workspace for semantic search (Consolidated Service Call).
        
        CRITICAL: This tool MUST be executed at the start of every project or session to enable semantic search and context retrieval.
        """
        logger.info(f"Indexing workspace: {project_root}")
        
        result = await memory_svc.index_workspace(project_root)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def search_semantic_memory(project_root: str, query: str, n_results: int = 5) -> str:
        """Advanced hybrid search across code and conceptual memory."""
        # Get keyword hits from filesystem first
        keyword_hits = file_svc.search_content(query, directory=project_root)
        results = await memory_svc.search(query, project_root, keyword_hits=keyword_hits, n=n_results)
        
        return json.dumps({
            "query": query,
            "project": project_root,
            "results": results,
            "note": "Hybrid Search: Exact keyword + Semantic vector matches."
        }, indent=2, ensure_ascii=False)
