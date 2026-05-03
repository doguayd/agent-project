from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
from utils.decorators import mcp_timeout
import os

def register_remote_ssh_tools(mcp: FastMCP, services: Dict[str, Any], config: Dict[str, Any]):
    """Registers tool for remote SSH execution via WSL and sshpass."""
    
    process_svc = services.get("process")
    diag_svc = services.get("diag")
    paths = config.get("paths", {})

    if not process_svc:
        return

    @mcp.tool()
    @mcp_timeout(seconds=30)
    async def remote_ssh_command(
        host: str,
        user: str,
        password: str,
        command: str
    ) -> Any:
        # line: 20
        """
        Executes a command on a remote server using sshpass through WSL.
        This provides a way to connect to remote servers from Windows environments 
        where sshpass is otherwise difficult to use.
        
        Args:
            host: Remote server hostname or IP.
            user: SSH username.
            password: SSH password.
            command: The command to execute on the remote server.
        """
        # Escape double quotes in the command to prevent shell breaking when nested
        escaped_command = command.replace('"', '\\"')
        
        # Build the final command string with 15s timeout for stability
        full_command = f'wsl sshpass -p "{password}" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {user}@{host} "{escaped_command}"'
        
        root = paths.get("PROJECT_ROOT") or os.getcwd()
        
        # Execute using process service
        return await process_svc.run_command(full_command, root)
