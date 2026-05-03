import os
import ast
import re
from typing import Dict, Any, Optional

class CodeInspector:
    """Detects logical code blocks surrounding a match line."""
    
    @staticmethod
    def get_code_block(file_path: str, match_line: int, preview_limit: int = 40) -> Dict[str, Any]:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content_str = f.read()
            lines = content_str.splitlines(keepends=True)
            idx = match_line - 1
            if idx >= len(lines): return {"line_start": match_line, "line_end": match_line, "code_preview": "", "node_type": "Snippet"}

            ext = os.path.splitext(file_path)[1].lower()
            start, end, symbol, node_type, confidence = idx, idx, None, "Snippet", 0.5
            
            # 1. AST (Python)
            if ext == ".py":
                try:
                    tree = ast.parse(content_str)
                    for node in ast.walk(tree):
                        if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                            if node.lineno <= match_line <= node.end_lineno:
                                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                    start, end = node.lineno - 1, node.end_lineno - 1
                                    symbol, node_type, confidence = node.name, ("FunctionDef" if not isinstance(node, ast.ClassDef) else "ClassDef"), 1.0
                                    break
                except SyntaxError: pass
            
            # 2. Heuristics (JS/TS/Fallback)
            if node_type == "Snippet":
                patterns = {
                    ".py": r"^\s*(def|class)\s+([a-zA-Z_]\w*)",
                    ".js": r"^\s*(async\s+)?(function|class|const|let|var)\s+([a-zA-Z_]\w*)",
                    ".ts": r"^\s*(async\s+)?(function|class|interface|type|enum|const)\s+([a-zA-Z_]\w*)",
                }
                pattern = patterns.get(ext)
                if pattern:
                    for i in range(idx, max(-1, idx - 40), -1):
                        m = re.search(pattern, lines[i])
                        if m:
                            start, symbol, confidence = i, m.group(m.lastindex), 0.8
                            node_type = "FunctionDef" if "def" in lines[i] or "function" in lines[i] else "ClassDef"
                            break
                            
            # Truncation logic
            end = max(end, idx)
            has_full_code = (end - start + 1) <= preview_limit
            code_fragment = "".join(lines[start:min(len(lines), start + preview_limit)]).strip()
            if not has_full_code: code_fragment += "\n... [Code Truncated] ..."
            
            return {
                "line_start": start + 1, "line_end": end + 1,
                "symbol": symbol, "node_type": node_type, 
                "symbol_confidence": confidence, "code_preview": code_fragment,
                "has_full_code": has_full_code
            }
        except:
            return {"line_start": match_line, "line_end": match_line, "code_preview": "", "node_type": "Snippet"}
