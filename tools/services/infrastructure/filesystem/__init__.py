from typing import List, Dict, Any, Optional
from .security import SecurityManager
from .io_manager import IOManager
from .reader import SmartReader
from .patcher import Patcher
from .search_engine import SearchEngine
from .inspector import CodeInspector

class FileSystemService:
    """Consolidated service for filesystem operations using modular components."""
    
    def __init__(self, allowed_roots: List[str], ignore_svc: Optional[Any] = None, 
                 bin_service: Optional[Any] = None, doc_svc: Optional[Any] = None, process_svc: Optional[Any] = None):
        self.security = SecurityManager(allowed_roots)
        self.io = IOManager()
        self.reader = SmartReader(doc_svc)
        self.patcher = Patcher()
        self.ignore_svc = ignore_svc
        self.process_svc = process_svc
        
        # Explorer integration
        from services.infrastructure.analysis.explorer import Explorer
        self.explorer = Explorer(str(self.security.allowed_roots[0]), ignore_svc)
        
        # Search engine depends on BinService
        if bin_service:
            self.searcher = SearchEngine(bin_service, str(self.security.allowed_roots[0]), process_service=process_svc)
        else:
            self.searcher = None

    def read_file(self, file_path: str, start_line: Optional[int] = None, 
                  end_line: Optional[int] = None, mode: str = "auto", doc_svc: Optional[Any] = None) -> str:
        resolved = self.security.resolve_path(file_path)
        # Use provided doc_svc if available, else fallback to the one from __init__
        reader = self.reader
        if doc_svc:
            from .reader import SmartReader
            reader = SmartReader(doc_svc)
        return reader.read(resolved, mode, start_line, end_line)

    def read_multiple(self, file_paths: List[str]) -> Dict[str, str]:
        results = {}
        for path in file_paths:
            try:
                results[path] = self.read_file(path)
            except Exception as e:
                results[path] = f"Error: {str(e)}"
        return results

    def write_file(self, file_path: str, content: str) -> str:
        resolved = self.security.resolve_path(file_path)
        self.io.write_file(resolved, content)
        return f"Successfully wrote to {file_path}"

    def list_directory(self, directory: str = ".") -> List[Dict[str, Any]]:
        resolved = self.security.resolve_path(directory)
        return self.io.list_directory(resolved)

    async def search_files(self, pattern: str, directory: str = ".") -> List[str]:
        if not self.searcher: return []
        return self.searcher.search_files(pattern, directory) # os.walk still sync but small

    async def search_content(self, query: str, directory: str = ".") -> List[Dict[str, Any]]:
        if not self.searcher: return [{"error": "Search engine not initialized."}]
        raw_matches = await self.searcher.search_content(query, directory)
        results = []
        for m in raw_matches:
            if "error" in m: continue
            block = CodeInspector.get_code_block(m["abs_path"], m["line"])
            results.append({
                "file": m["file"],
                "symbol": block.get("symbol"),
                "node_type": block.get("node_type"),
                "score": 0.8,
                "line_start": block.get("line_start"),
                "line_end": block.get("line_end"),
                "code_preview": block.get("code_preview")
            })
        return results

    def multi_edit_file(self, file_path: str, chunks: List[Dict[str, str]]) -> str:
        resolved = self.security.resolve_path(file_path)
        return self.patcher.multi_edit(resolved, chunks)

    def create_directory(self, directory: str) -> str:
        resolved = self.security.resolve_path(directory)
        self.io.create_directory(resolved)
        return f"Directory created: {directory}"

    def move_file(self, source_path: str, dest_path: str) -> str:
        src = self.security.resolve_path(source_path)
        dst = self.security.resolve_path(dest_path)
        return self.io.move_item(src, dst)

    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        resolved = self.security.resolve_path(file_path)
        return self.io.get_file_info(resolved)

    def diff_file_range_with_string(self, file_path: str, text: str, 
                                   start_line: Optional[int] = None, 
                                   end_line: Optional[int] = None,
                                   context_lines: int = 3) -> str:
        resolved = self.security.resolve_path(file_path)
        return self.patcher.diff_file_range_with_string(resolved, text, start_line, end_line, context_lines)

    def apply_patch(self, target_path: str, patch_text: str) -> str:
        resolved = self.security.resolve_path(target_path)
        return self.patcher.apply_patch(resolved, patch_text)

    def directory_tree(self, directory: str = ".", max_depth: int = 3) -> str:
        # Use explorer to generate the tree
        # If the directory is within allowed roots, resolve_path will handle it
        resolved_dir = self.security.resolve_path(directory)
        # We need a relative path from the security manager's base if we want to use explorer's logic,
        # but explorer takes its own project_root. Let's make it simple.
        return self.explorer.get_tree(directory, max_depth)
