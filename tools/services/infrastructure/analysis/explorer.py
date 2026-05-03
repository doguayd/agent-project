import os
import json
import pathlib
from typing import List, Dict, Any, Optional

class Explorer:
    """Provides high-level directory visualization and tree structures."""
    
    def __init__(self, project_root: str, ignore_svc: Optional[Any] = None):
        self.project_root = pathlib.Path(project_root).resolve()
        self.ignore_svc = ignore_svc

    def get_tree(self, directory: str = ".", max_depth: int = 3) -> str:
        target_dir = (self.project_root / directory).resolve()
        nodes = []
        
        def _scan(cur_path, depth=0):
            if depth > max_depth: return
            rel_path = os.path.relpath(cur_path, self.project_root)
            if self.ignore_svc and self.ignore_svc.is_ignored(rel_path, is_dir=os.path.isdir(cur_path)):
                return

            is_dir = os.path.isdir(cur_path)
            nodes.append({
                "path": os.path.relpath(cur_path, target_dir).replace("\\", "/"),
                "type": "directory" if is_dir else "file",
                "depth": depth,
                "role": self._infer_role(cur_path, is_dir)
            })
            
            if is_dir:
                try:
                    for item in sorted(os.listdir(cur_path)):
                        _scan(os.path.join(cur_path, item), depth + 1)
                except: pass

        _scan(target_dir)
        return json.dumps({"root": directory, "nodes": nodes}, indent=2)

    def _infer_role(self, path: str, is_dir: bool) -> str:
        p = str(path).lower()
        if "main.py" in p or "app.py" in p: return "entrypoint"
        if "services/" in p: return "service"
        if "tests/" in p: return "test"
        return "directory" if is_dir else "logic"
