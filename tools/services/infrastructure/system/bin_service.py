import sys
import platform
import os
from pathlib import Path
from services.core.logger_service import setup_logger

logger = setup_logger("BinService")

class BinService:
    """Service to resolve platform-specific binary paths."""
    
    def __init__(self, project_root: str = None):
        # We find the server home relative to this file
        # After refactoring, this file is in services/infrastructure/system/
        # so we need to go up 3 levels to reach the project root (mcp_master)
        self.server_home = Path(__file__).parents[3].resolve()
        
        # Binary resolution should ALWAYS be relative to the server source
        # After reorganization, it's now in resources/bin
        self.bin_root = self.server_home / "resources" / "bin"
            
        self.os_name = sys.platform  # 'win32', 'linux', etc.
        self.machine = platform.machine().lower()  # 'amd64', 'x86_64', 'arm64', etc.
        
        # Normalize architecture for our structure
        if "64" in self.machine:
            if "arm" in self.machine or "aarch64" in self.machine:
                self.arch = "arm64"
            else:
                self.arch = "x64"
        else:
            self.arch = "x86"
            
        logger.info(f"BinService initialized. Platform: {self.os_name}, Arch: {self.arch}")

    def get_binary_path(self, tool_name: str) -> Path:
        """
        Resolves the path for a specific tool.
        Checks bin/<os>/<arch>/ and then system PATH.
        """
        # 1. Check local bin directory
        bin_ext = ".exe" if self.os_name == "win32" else ""
        local_path = self.bin_root / self.os_name / self.arch / f"{tool_name}{bin_ext}"
        
        if local_path.exists():
            logger.debug(f"Resolved {tool_name} to local path: {local_path}")
            return local_path
            
        # 2. Check system PATH
        # We can use 'where' on Windows or 'which' on Linux, or just rely on subprocess
        # but for resolution we can check if it exists in PATH
        import shutil
        system_path = shutil.which(tool_name)
        if system_path:
            logger.debug(f"Resolved {tool_name} to system path: {system_path}")
            return Path(system_path)
            
        logger.warning(f"Could not resolve binary for tool: {tool_name}")
        return None

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available either locally or in PATH."""
        return self.get_binary_path(tool_name) is not None

    def check_all_bins(self) -> dict:
        """Check availability of all required tools."""
        tools = ["ruff", "rg", "oxlint", "biome"]
        results = {}
        for tool in tools:
            results[tool] = self.is_tool_available(tool)
        return results
