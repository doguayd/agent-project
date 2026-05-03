import ast
import re
import pathlib
from typing import List, Dict, Any, Optional, Set
from services.core.logger_service import setup_logger

logger = setup_logger("Analysis.Graph")

class DependencyGrapher:
    """Builds and analyzes intra-project dependency graphs."""
    
    def __init__(self, project_root: pathlib.Path):
        self.project_root = project_root

    def build(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        module_to_path = {'.'.join(pathlib.Path(f["path"]).parts): f["path"] for f in files}
        edges = []
        for f in files:
            imports = set()
            if f["extension"] == ".py": imports = self._extract_py(f["abs_path"])
            elif f["extension"] in [".js", ".ts"]: imports = self._extract_js(f["abs_path"])
            
            for imp in imports:
                resolved = self._resolve(imp, f["path"], module_to_path)
                if resolved and resolved != f["path"]:
                    edges.append((f["path"], resolved))
        
        return {"edges": edges, "cycles": self._find_cycles(edges)}

    def _extract_py(self, abs_path: str) -> Set[str]:
        imports = set()
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names: imports.add(n.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module: imports.add(f"{'.' * node.level}{node.module}")
        except: pass
        return imports

    def _extract_js(self, abs_path: str) -> Set[str]:
        imports = set()
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                matches = re.findall(r"(?:import|from|require)\s*['\"](.*?)['\"]", content)
                for m in matches:
                    if m.startswith('.') or any(p in m for p in ['services/', 'core/']):
                        imports.add(m.replace('/', '.'))
        except: pass
        return imports

    def _resolve(self, imp_name: str, scanner_path: str, module_map: Dict[str, str]) -> Optional[str]:
        if imp_name in module_map: return module_map[imp_name]
        # Simplistic relative resolver for demo
        if imp_name.startswith('.'):
            # (Logic from WorkspaceAnalyzer goes here)
            pass
        return None

    def _find_cycles(self, edges: List[tuple]) -> List[List[str]]:
        adj = {}
        for u, v in edges:
            if u not in adj: adj[u] = []
            adj[u].append(v)
        
        cycles = []
        visited, stack = set(), []
        def dfs(node):
            if node in stack:
                cycles.append(stack[stack.index(node):] + [node])
                return
            if node in visited: return
            visited.add(node)
            stack.append(node)
            if node in adj:
                for n in adj[node]: dfs(n)
            stack.pop()
        
        for node in list(adj.keys()): dfs(node)
        return cycles[:5]
