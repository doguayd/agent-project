import json
import pathlib
from typing import Optional, List
from fastmcp import FastMCP
from utils.decorators import mcp_timeout
from resources.config.settings import PROJECT_ROOT, PROJECT_ID, ALLOWED_ROOTS, get_project_entry
from services.infrastructure.analysis import WorkspaceAnalyzerService
from services.infrastructure.system.ignore_service import IgnoreService

def register_workspace_tools(mcp: FastMCP, workspace_svc):
    
    @mcp.tool()
    @mcp_timeout(seconds=90)
    async def workspace_summary(
        project_root: Optional[str] = None, 
        mode: str = "fast", 
        max_depth: int = 5
    ) -> str:
        """
        Comprehensive workspace analyzer tool. 
        Extracts structure, technology, entrypoints, modules, and multi-factor hotspots.
        
        CRITICAL: This tool MUST be executed at the start of every project or session to understand the architecture and project structure.

        Args:
            project_root: Path to investigate (defaults to allowed root).
            mode: 'fast' (metadata only) or 'deep' (AST analysis, imports, health scores).
            max_depth: Maximum directory depth for scanning.
            
        Use this tool when entering a new project or investigating technical debt/hotspots.
        """
        try:
            target_analyzer = workspace_svc
            
            if project_root:
                # Security Check: Ensure the path is within allowed roots
                target_path = pathlib.Path(project_root).resolve()
                is_allowed = False
                for root in ALLOWED_ROOTS:
                    try:
                        if target_path.is_relative_to(pathlib.Path(root).resolve()):
                            is_allowed = True
                            break
                    except AttributeError:
                        # Fallback for older python versions (<3.9) although we expect 3.9+
                        if str(target_path).startswith(str(pathlib.Path(root).resolve())):
                            is_allowed = True
                            break
                
                if not is_allowed:
                    return f"Security Error: Access to '{project_root}' is denied. It must be inside ALLOWED_ROOTS."
                
                # Dynamic Ignore Service for the target project
                # Uses the same global default_ignores but loads target's .gitignore
                new_ignore_svc = IgnoreService(
                    workspace_svc.ignore_svc.default_ignore_path,
                    project_root
                )

                # Create a temporary analyzer for the custom root
                target_analyzer = WorkspaceAnalyzerService(project_root, ignore_svc=new_ignore_svc)

            result = target_analyzer.analyze(mode=mode, max_depth=max_depth)
            
            # Enrich with registry metadata if available
            entry = get_project_entry(str(target_analyzer.project_root))
            if entry and "metadata" in entry:
                result["ledger"] = {
                    "last_indexed": entry["metadata"].get("last_indexed"),
                    "file_count": entry["metadata"].get("file_count"),
                    "languages": entry["metadata"].get("language_distribution")
                }
                
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Analysis failed: {str(e)}"
