import os
from typing import Any, Optional

class SmartReader:
    """Unified reader for text and rich documents with truncation logic."""
    
    def __init__(self, doc_svc: Optional[Any] = None):
        self.doc_svc = doc_svc

    def read(self, target_file: str, mode: str = "auto", 
             start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        ext = os.path.splitext(target_file)[1].lower()
        
        if mode == "auto":
            mode = "rich" if ext in ['.pdf', '.docx', '.epub'] else "text"

        if mode == "rich":
            if not self.doc_svc:
                return "Error: Document service not available for rich content."
            content = self.doc_svc.extract_text(target_file)
            return self._apply_limits(content, limit=50000, is_rich=True) if content else "Error: Extraction failed."

        # Text Mode
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                if start_line or end_line:
                    lines = f.readlines()
                    start = (start_line - 1) if start_line else 0
                    end = end_line if end_line else len(lines)
                    content = "".join(lines[start:end])
                else:
                    content = f.read()
            
            processed = self._apply_limits(content, limit=None)
            return self._wrap_syntax(processed, ext)
        except UnicodeDecodeError:
            return "Error: Encoding mismatch. Try 'rich' mode or check if binary."

    def _apply_limits(self, text: str, limit: Optional[int], is_rich: bool = False) -> str:
        if not limit or len(text) <= limit: return text
        truncated_point = text.rfind('\n', 0, limit)
        if truncated_point == -1: truncated_point = limit
        
        info = f"\n\n[Content truncated. Total: {len(text)} chars]"
        return text[:truncated_point] + info

    def _wrap_syntax(self, content: str, extension: str) -> str:
        ext_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.html': 'html', '.css': 'css', '.json': 'json',
            '.md': 'markdown', '.yml': 'yaml', '.yaml': 'yaml',
            '.sql': 'sql', '.sh': 'bash', '.ps1': 'powershell'
        }
        lang = ext_map.get(extension)
        return f"```{lang}\n{content}\n```" if lang else content
