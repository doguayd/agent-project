import os
import json
import asyncio
import subprocess
from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("SearchEngine")

class SearchEngine:
    """Orchestrates fast text searches using Ripgrep binary."""
    
    def __init__(self, bin_service: Any, project_root: str, process_service: Optional[Any] = None):
        self.bin_service = bin_service
        self.project_root = project_root
        self.process_service = process_service

    def search_files(self, pattern: str, directory: str = ".") -> List[str]:
        """Search for files matching a pattern (case-insensitive)."""
        matches = []
        target_dir = os.path.join(self.project_root, directory)
        for root, _, files in os.walk(target_dir):
            for name in files:
                if pattern.lower() in name.lower():
                    matches.append(os.path.relpath(os.path.join(root, name), self.project_root))
        return matches

    async def search_content(self, query: str, directory: str = ".") -> List[Dict[str, Any]]:
        """LLM-Optimized content search using Ripgrep."""
        return await asyncio.to_thread(self._sync_search_content, query, directory)

    def _sync_search_content(self, query: str, directory: str = ".", includes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        rg_path = self.bin_service.get_binary_path("rg")
        if not rg_path: return [{"error": "Ripgrep not found."}]

        target_dir = os.path.join(self.project_root, directory)
        try:
            cmd = [str(rg_path), "--files-with-matches", query, target_dir]
            if includes:
                for inc in includes:
                    cmd.extend(["-g", f'"{inc}"'])
            
            # Use Popen to get PID before wait()
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            
            # Register for Reaper if service available
            if self.process_service:
                self.process_service.register_process_to_request(process.pid)
            
            stdout, stderr = process.communicate()
            
            matches = []
            for line in stdout.splitlines():
                try:
                    data = json.loads(line)
                    if data.get("type") == "match":
                        payload = data.get("data")
                        abs_path = payload.get("path", {}).get("text")
                        matches.append({
                            "file": os.path.relpath(abs_path, self.project_root),
                            "line": payload.get("line_number"),
                            "abs_path": abs_path
                        })
                except: continue
            return matches[:50]
        except Exception as e:
            return [{"error": str(e)}]
