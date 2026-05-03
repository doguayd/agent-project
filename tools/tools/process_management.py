import os
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

def register_process_tools(mcp: FastMCP, services: Dict[str, Any], config: Dict[str, Any]):
    """Registers unified background work management tool."""
    
    process_svc = services["process"]
    async_task_svc = services.get("async_task")
    diag_svc = services.get("diag")
    paths = config.get("paths", {})

    @mcp.tool()
    async def manage_background_job(
        action: str, 
        identifier: Optional[str] = None, 
        tail: int = 50,
        project_root: Optional[str] = None
    ) -> Any:
        """
        Unified tool for managing background OS processes and internal system tasks.
        
        Actions:
        - run: Start a new background terminal command. 'identifier' is the command string.
        - status: Check status/output of a job. 'identifier' is the task_id.
        - stop: Terminate a job. 'identifier' is the task_id.
        - list: List all active background processes and system tasks.
        - search: Find system processes by name. 'identifier' is the process name.
        """
        if action == "run":
            if not identifier: return "Error: 'identifier' (command) is required for action 'run'."
            root = project_root or paths.get("PROJECT_ROOT") or os.getcwd()
            return await process_svc.run_command(identifier, root)
            
        elif action == "status":
            if not identifier: return "Error: 'identifier' (task_id) is required for action 'status'."
            # Try external processes first
            status = process_svc.get_status(identifier, tail=tail)
            if status.get("status") != "error":
                return status
            # Fallback to internal tasks
            if async_task_svc:
                return async_task_svc.get_status(identifier)
            return status

        elif action == "stop":
            if not identifier: return "Error: 'identifier' (task_id) is required for action 'stop'."
            return process_svc.stop_task(identifier)
            
        elif action == "list":
            return {
                "OS_Processes": process_svc.list_tasks(),
                "Internal_Tasks": async_task_svc.list_tasks() if async_task_svc else []
            }
            
        elif action == "search":
            if not identifier: return "Error: 'identifier' (name) is required for action 'search'."
            if not diag_svc: return "Error: DiagnosticService not available."
            results = diag_svc.find_process(identifier)
            if not results:
                return f"No process found matching '{identifier}'."
            return results
            
        return f"Error: Unknown action '{action}'. Valid actions are: run, status, stop, list, search."
