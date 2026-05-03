import json
import os
import re
from typing import Optional, List
from fastmcp import FastMCP
from utils.decorators import mcp_timeout

def register_file_tools(mcp: FastMCP, file_svc, diag_svc, doc_svc=None):
    @mcp.tool()
    async def read_file(file_path: str, mode: str = "auto", start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        """
        Smart unified file reader for text and rich documents (PDF, DOCX, EPUB).
        
        Args:
            file_path: Path to the target file.
            mode: 'auto' (detect), 'text' (force text), or 'rich' (force doc extraction).
            start_line: Starting line number for text files (1-indexed).
            end_line: Ending line number for text files (inclusive).
            
        Note: For PDF/DOCX, line parameters are ignored and 50k char limit applies.
        Text files > 5MB require line ranges for safety.
        """
        try:
            return file_svc.read_file(file_path, start_line, end_line, mode=mode, doc_svc=doc_svc)
        except Exception as e:
            return str(e)


    @mcp.tool()
    async def read_multiple_files(file_paths: List[str]) -> str:
        """Read multiple files at once."""
        try:
            res = file_svc.read_multiple(file_paths)
            return "\n".join([f"--- {p} ---\n{c}" for p, c in res.items()])
        except Exception as e: return str(e)

    @mcp.tool()
    async def write_file(file_path: str, content: str) -> str:
        """Write or overwrite a file."""
        try: return file_svc.write_file(file_path, content)
        except Exception as e: return str(e)

    @mcp.tool()
    async def multi_replace_file_content(file_path: str, chunks: List[dict]) -> str:
        """
        Apply multiple find-and-replace edits to a file in a single atomic operation.
        Each chunk must contain 'target' (the exact text to find) and 'replacement' (the new text).
        The operation is atomic: if any target chunk is not found, no changes are applied.
        """
        try: return file_svc.multi_edit_file(file_path, chunks)
        except Exception as e: return str(e)



    @mcp.tool()
    @mcp_timeout(seconds=30)
    async def directory_tree(directory: str = ".", max_depth: int = 3) -> str:
        """
        Returns a flattened 'Indexed File Graph' of the directory, optimized for AI reasoning.
        Provides rich metadata (sizes, counts, types, roles) and respects .gitignore rules.
        """
        try: return file_svc.directory_tree(directory, max_depth)
        except Exception as e: return str(e)


    @mcp.tool()
    @mcp_timeout(seconds=10)
    async def search_files(pattern: str, directory: str = ".") -> str:
        """Search for files matching a pattern."""
        err = await diag_svc.check_tool_dependency("search_files")
        if err: return err
        try:
            matches = await file_svc.search_files(pattern, directory)
            return "Matches: " + ", ".join(matches) if matches else "No matches found."
        except Exception as e: return str(e)

    @mcp.tool()
    async def get_file_info(file_path: str) -> str:
        """Get detailed metadata for a file."""
        try: return json.dumps(file_svc.get_file_info(file_path), indent=2)
        except Exception as e: return str(e)



    # --- Feature: Diff & Patch ---

    @mcp.tool()
    async def diff_file_range_with_string(target_file: str, text: str, 
                                         start_line: Optional[int] = None, 
                                         end_line: Optional[int] = None, 
                                         context_lines: int = 3) -> str:
        """
        Bir dosyanın belirli bir satır aralığını sağlanan bir metin içeriğiyle karşılaştırır.
        
        Args:
            target_file: Karşılaştırılacak dosyanın yolu.
            text: Dosya içeriğiyle karşılaştırılacak ham metin (string).
            start_line: Dosyanın okunmaya başlanacağı satır (1-indexed, opsiyonel).
            end_line: Dosyanın okunacağı son satır (dahil, opsiyonel).
            context_lines: Diff çıktısında gösterilecek bağlam satır sayısı (varsayılan: 3).
        """
        try:
            return file_svc.diff_file_range_with_string(target_file, text, start_line, end_line, context_lines)
        except Exception as e:
            return str(e)

    @mcp.tool()
    async def apply_patch(target_path: str, patch_text: str) -> str:
        """Apply a unified diff patch to a file in-place."""
        try:
            return file_svc.apply_patch(target_path, patch_text)
        except Exception as e:
            return str(e)

