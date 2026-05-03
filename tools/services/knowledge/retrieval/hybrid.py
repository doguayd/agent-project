from typing import List, Dict, Any, Optional

class HybridResolver:
    """Merges and ranks results from keyword (Ripgrep) and semantic (Vector) search."""
    
    @staticmethod
    def resolve(query: str, keyword_hits: List[Dict], vector_hits: List[Dict], n: int = 5) -> List[Dict]:
        results = []
        
        # 1. Process Keyword Hits (Ripgrep)
        for hit in keyword_hits:
            results.append({
                "source": "Keyword Search (Exact Block Match)",
                "content": hit.get("code_preview") or hit.get("content"),
                "file": hit.get("file"),
                "score": hit.get("score", 0.9),
                "metadata": hit.get("metadata", {})
            })
            
        # 2. Process Vector Hits
        for hit in vector_hits:
            results.append({
                "source": "Vector Search (Conceptual Match)",
                "content": hit.get("content"),
                "file": hit.get("metadata", {}).get("path", "memory"),
                "score": hit.get("score", 0.7),
                "metadata": hit.get("metadata", {})
            })
            
        # 3. Sort by score and drop duplicates
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:n]
