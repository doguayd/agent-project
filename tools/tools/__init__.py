from .ai_assistant import register_ai_tools
from .reasoning import register_reasoning_tools
from .research import register_research_tools
from .file_ops import register_file_tools
from .memory import register_memory_tools
from .task_management import register_task_tools
from .diagnostics import register_diagnostic_tools
from .process_management import register_process_tools
from .remote_ssh import register_remote_ssh_tools
from .workspace import register_workspace_tools


def register_all_tools(mcp, services, paths):
    diag_svc = services['diag']
    
    register_ai_tools(mcp, services['ollama'], services['prompt'], diag_svc, services['file'], services.get('async_task'))
    register_reasoning_tools(mcp, services['thinking'], diag_svc, paths['PROJECT_ROOT'])
    register_research_tools(mcp, services['search'], services['validator'], services['stackoverflow'], diag_svc, services.get('http'))
    register_file_tools(mcp, services['file'], diag_svc, services.get('doc'))
    register_memory_tools(mcp, services['memory'], services['task'], services['doc'], paths['PROJECT_ROOT'], services['logger'], diag_svc, services['ignore'], services['file'], services.get('async_task'))
    
    # register_rich_doc_tools removed - functionality integrated into register_file_tools
    register_task_tools(mcp, services['task'], services['planner'], diag_svc)
    register_workspace_tools(mcp, services['workspace'])
    
    register_diagnostic_tools(
        mcp, 
        services['diag'],
        paths['audit_logs'], 
        paths['memory'], 
        paths['PROJECT_ROOT'], 
        paths['SERVER_HOME'],
        services.get('process')
    )
    
    if 'process' in services:
        register_process_tools(mcp, services, {'paths': paths})
        register_remote_ssh_tools(mcp, services, {'paths': paths})
