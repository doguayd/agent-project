import pathlib
import time
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from resources.config.settings import get_project_entry, save_to_registry, get_project_id, PROJECT_ID, resolve_paths
from .scanner import MetadataScanner
from .graph import DependencyGrapher
from .metrics import ImpactEvaluator
from .architect import Architect
from .explorer import Explorer
from services.core.logger_service import setup_logger

logger = setup_logger("Analysis.Analyzer")

class WorkspaceAnalyzerService:
    """Consolidated service for workspace analysis using modular components."""
    
    def __init__(self, project_root: str, ignore_svc: Optional[Any] = None):
        self.project_root = pathlib.Path(project_root).resolve()
        self.ignore_svc = ignore_svc
        self.scanner = MetadataScanner(self.project_root, ignore_svc)
        self.grapher = DependencyGrapher(self.project_root)
        self.explorer = Explorer(str(self.project_root), ignore_svc)
        self.architect = Architect()

    def analyze(self, mode: str = "fast", max_depth: int = 5) -> Dict[str, Any]:
        # Get project-specific central storage path
        paths = resolve_paths(str(self.project_root))
        local_cache_path = pathlib.Path(paths["LOCAL_DATA"]) / "summary.json"
        
        # --- PHASE 0: Cache Check ---
        # 1. Try local cache first for mobility
        if mode == "fast" and local_cache_path.exists():
            try:
                with open(local_cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    last_summary = cached_data.get("_cache_info", {}).get("timestamp")
                    if last_summary:
                        last_time = datetime.fromisoformat(last_summary)
                        if (datetime.now() - last_time).total_seconds() < 12 * 3600:
                            cached_data["_cache_info"]["status"] = "LOCAL_CACHED"
                            return cached_data
            except Exception: pass

        # 2. Central Registry Fallback
        entry = get_project_entry(str(self.project_root))
        if entry and mode == "fast":
            metadata = entry.get("metadata", {})
            last_summary = metadata.get("last_summary")
            summary_cache = metadata.get("summary_cache")
            
            if last_summary and summary_cache:
                try:
                    # Check for 12h freshness
                    last_time = datetime.fromisoformat(last_summary)
                    if (datetime.now() - last_time).total_seconds() < 12 * 3600:
                        summary_cache["_cache_info"] = {
                            "status": "CACHED",
                            "timestamp": last_summary,
                            "note": "Result served from project ledger (cache < 12h)."
                        }
                        
                        # Fix: If central cache is hit but local file is missing, sync it
                        if not local_cache_path.exists():
                            try:
                                with open(local_cache_path, 'w', encoding='utf-8') as f:
                                    json.dump(summary_cache, f, indent=2)
                            except: pass
                            
                        return summary_cache
                except: pass # Fallback to fresh scan if date parsing fails

        # --- PHASE 1: Fresh Scan ---
        scan_result = self.scanner.scan(max_depth)
        files_data = scan_result["files"]
        
        # Language distribution calculation (using pre-computed scanner values)
        language_stats = {}
        for f in files_data:
            lang = f.get("language", "text")
            language_stats[lang] = language_stats.get(lang, 0) + 1

        summary = {
            "project_root": str(self.project_root),
            "stats": {
                "files": len(files_data), 
                "directories": scan_result["directory_count"],
                "total_size_bytes": scan_result["total_size_bytes"],
                "language_distribution": language_stats,
                "markers": list(set(f["role"] for f in files_data if f.get("is_marker")))
            },
            "mode": mode,
            "architecture": self.architect.guess_architecture(files_data)
        }

        if mode == "deep":
            graph_data = self.grapher.build(files_data)
            hotspots = ImpactEvaluator.calculate_hotspots(files_data, graph_data["edges"])
            health = ImpactEvaluator.get_health_metrics(len(files_data), len(graph_data["edges"]))
            
            result = {
                "summary": summary,
                "hotspots": hotspots[:10],
                "health": health,
                "signals": {"circular_dependencies": graph_data["cycles"]}
            }
        else:
            # Build an optimized structural view for LLM context
            folders = {}
            for f in files_data:
                parts = f['path'].split('/')
                if len(parts) > 1:
                    folder = parts[0]
                    folders[folder] = folders.get(folder, 0) + 1
            
            result = {
                "summary": summary,
                "structure_preview": {
                    "top_level_folders": folders,
                    "main_components": list(folders.keys())
                }
            }
        
        # --- PHASE 2: Update Cache (Central + Local) ---
        result["_cache_info"] = {"status": "FRESH", "timestamp": datetime.now().isoformat()}
        
        # Enrich with ledger info from registry if available
        if entry and "metadata" in entry:
            result["ledger"] = {
                "last_indexed": entry["metadata"].get("last_indexed"),
                "file_count": entry["metadata"].get("file_count"),
                "languages": entry["metadata"].get("language_distribution")
            }

        # Update Central Registry
        save_to_registry(str(self.project_root), get_project_id(str(self.project_root)), metadata={
            "last_summary": datetime.now().isoformat(),
            "summary_cache": result
        })

        # Persist Centrally in MCP Project Directory
        try:
            os.makedirs(os.path.dirname(local_cache_path), exist_ok=True)
            with open(local_cache_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save summary cache to {local_cache_path}: {e}")

        return result

    def directory_tree(self, directory: str = ".", max_depth: int = 3) -> str:
        return self.explorer.get_tree(directory, max_depth)
