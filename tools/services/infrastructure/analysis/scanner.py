import os
import pathlib
import json
import fnmatch
from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("Analysis.Scanner")

class MetadataScanner:
    """Fast recursive scanner for project metadata."""
    
    def __init__(self, project_root: pathlib.Path, ignore_svc: Optional[Any] = None):
        self.project_root = project_root
        self.ignore_svc = ignore_svc
        
        # Load centralized mappings
        server_home = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        config_dir = os.path.join(server_home, "resources", "config")
        
        self.lang_map = self._load_json(os.path.join(config_dir, "languages.json"), {})
        raw_markers = self._load_json(os.path.join(config_dir, "file_markers.json"), {})
        
        # Categorize markers for performance
        self.exact_markers = {}
        self.pattern_markers = {} # for globs like *.csproj
        self.path_markers = {}    # for subpaths like .github/workflows
        
        for k, v in raw_markers.items():
            if "*" in k:
                self.pattern_markers[k] = v
            elif "/" in k or "\\" in k:
                # Normalize path and store
                norm_k = k.replace("\\", "/").strip("/")
                self.path_markers[norm_k] = v
            else:
                self.exact_markers[k] = v

    def _load_json(self, path: str, default: Any) -> Any:
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config {path}: {e}")
        return default

    def scan(self, max_depth: int = 5) -> Dict[str, Any]:
        results = []
        directory_count = 0
        total_size_bytes = 0
        for root, dirs, files in os.walk(self.project_root):
            rel_root = os.path.relpath(root, self.project_root)
            depth = 0 if rel_root == "." else len(rel_root.split(os.sep))
            if depth > max_depth: continue

            if self.ignore_svc:
                dirs[:] = [d for d in dirs if not self.ignore_svc.is_ignored(os.path.join(rel_root, d), is_dir=True)]
                files = [f for f in files if not self.ignore_svc.is_ignored(os.path.join(rel_root, f), is_dir=False)]

            directory_count += 1
            for file in files:
                file_path = pathlib.Path(root) / file
                ext = file_path.suffix.lower()
                filename = file_path.name
                rel_file_path = os.path.relpath(file_path, self.project_root).replace("\\", "/")
                
                # Priority-based Discovery
                role = None
                
                # 1. Exact Name Match (O(1))
                role = self.exact_markers.get(filename)
                
                # 2. Pattern Match (Globs like *.csproj)
                if not role:
                    for pattern, p_role in self.pattern_markers.items():
                        if fnmatch.fnmatch(filename, pattern):
                            role = p_role
                            break
                            
                # 3. Path/Folder Match (like .github/workflows)
                if not role:
                    for path_marker, p_role in self.path_markers.items():
                        if rel_file_path.startswith(path_marker):
                            role = p_role
                            break
                            
                is_marker = role is not None
                
                # Identify Language
                lang = self.lang_map.get(ext, "text")

                try:
                    stat = file_path.stat()
                    total_size_bytes += stat.st_size
                    results.append({
                        "path": rel_file_path,
                        "abs_path": str(file_path),
                        "size": stat.st_size,
                        "extension": ext,
                        "language": lang,
                        "role": role,
                        "is_marker": is_marker
                    })
                except: continue
        return {
            "files": results,
            "directory_count": directory_count,
            "total_size_bytes": total_size_bytes
        }

    def get_language(self, ext: str) -> str:
        """Helper to get language from extension using loaded map."""
        return self.lang_map.get(ext.lower(), 'text')
