import os
import json
import hashlib
import time
from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger
from services.infrastructure.analysis.scanner import MetadataScanner
from resources.config.settings import save_to_registry, get_project_id

logger = setup_logger("Knowledge.Indexer")

class WorkspaceIndexer:
    """Handles deep indexing of workspaces for semantic memory."""
    
    def __init__(self, knowledge_svc: Any, ignore_svc: Any, doc_svc: Any):
        self.knowledge = knowledge_svc
        self.ignore = ignore_svc
        self.doc = doc_svc

    async def index_workspace(self, project_root: str, max_size: int = 1048576) -> Dict[str, Any]:
        """Scans and indexes a workspace incrementally."""
        indexed, deleted, skipped = 0, 0, 0
        text_exts = {'.py', '.md', '.txt', '.json', '.yaml', '.js', '.ts', '.html', '.css'}
        
        # Determine the correct semantic engine for THIS project root
        semantic_engine = self.knowledge.get_semantic_engine(project_root)
        
        # 0. Cleanup Stale Entries (Phase 0)
        indexed_paths = semantic_engine.get_indexed_paths()
        logger.info(f"Cleanup | Found {len(indexed_paths)} total entries in semantic memory for {project_root}.")
        for rel_path in indexed_paths:
            full_path = os.path.normpath(os.path.join(project_root, rel_path))
            exists = os.path.exists(full_path)
            if not exists:
                logger.info(f"Cleanup | Removing stale entry: {rel_path}")
                await semantic_engine.delete_by_path(rel_path)
                deleted += 1

        # 1. Gather files
        files_to_index = []
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if not self.ignore.is_ignored(os.path.relpath(os.path.join(root, d), project_root), is_dir=True)]
            for f in files:
                rel_path = os.path.relpath(os.path.join(root, f), project_root)
                if not self.ignore.is_ignored(rel_path, is_dir=False):
                    files_to_index.append(os.path.join(root, f))

        # 2. Process Files (Incremental using Hash/Mtime)
        for full_path in files_to_index:
            try:
                if os.path.getsize(full_path) > max_size:
                    skipped += 1
                    continue
                
                ext = os.path.splitext(full_path)[1].lower()
                rel_path = os.path.relpath(full_path, project_root)
                
                if ext in text_exts:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # Modular indexing call
                    await semantic_engine.index(content, {"path": rel_path}, rel_path)
                    indexed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(f"Failed to index {full_path}: {e}")
                
        # 3. Aggregate Stats & Update Registry
        language_stats = {}
        for full_path in files_to_index:
            ext = os.path.splitext(full_path)[1].lower()
            lang = MetadataScanner.get_language(ext)
            language_stats[lang] = language_stats.get(lang, 0) + 1

        stats = {
            "indexed": indexed, 
            "deleted": deleted, 
            "skipped": skipped,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S'),
            "languages": language_stats
        }

        # Update central registry
        project_id = get_project_id(project_root)
        save_to_registry(project_root, project_id, metadata={
            "last_indexed": stats["timestamp"],
            "file_count": len(files_to_index),
            "language_distribution": language_stats
        })
                
        return stats
