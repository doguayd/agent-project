import math
import time
from typing import List, Dict, Any, Optional
from collections import defaultdict, deque
from services.core.logger_service import setup_logger

logger = setup_logger("Analysis.Metrics")

class ImpactEvaluator:
    """Calculates risk levels and hotspots based on code centrality and volatility."""
    
    @staticmethod
    def calculate_hotspots(files: List[Dict[str, Any]], edges: List[tuple]) -> List[Dict[str, Any]]:
        # 1. Degrees
        in_degree = defaultdict(int)
        for u, v in edges: in_degree[v] += 1
        
        # 2. Score Normalization (Percentiles)
        max_centrality = max(in_degree.values()) if in_degree else 1
        
        hotspots = []
        for f in files:
            path = f["path"]
            centrality = in_degree.get(path, 0) / max_centrality
            size_score = math.log10(f["size"] + 1) / 7.0 # Normalize 10MB to ~1.0
            
            total_score = (centrality * 0.6 + size_score * 0.4) * 100
            
            hotspots.append({
                "path": path,
                "score": round(total_score, 1),
                "risk_level": "high" if total_score > 70 else "medium" if total_score > 40 else "low"
            })
            
        return sorted(hotspots, key=lambda x: x["score"], reverse=True)

    @staticmethod
    def get_health_metrics(files_count: int, edges_count: int) -> Dict[str, float]:
        if files_count == 0: return {"coupling": 0.0, "modularity": 0.0}
        avg_coupling = edges_count / files_count
        norm_coupling = 1.0 / (1.0 + avg_coupling)
        return {
            "coupling_score": round(norm_coupling, 2),
            "modularity_score": round(norm_coupling * 0.8, 2) # Heuristic
        }
