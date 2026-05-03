import os
import sys
from pathlib import Path

# Ensure the project root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastmcp import FastMCP
from resources.config.settings import PROJECT_ROOT, PATHS, SERVER_HOME, ALLOWED_ROOTS, STACK_EXCHANGE_API_KEY, ensure_directories
from services.core.logger_service import setup_logger, log_startup_banner
from utils.decorators import set_process_service_reference

# Modular Service Imports - Infrastructure
from services.infrastructure.filesystem import FileSystemService
from services.infrastructure.analysis import WorkspaceAnalyzerService
from services.infrastructure.system.bin_service import BinService
from services.infrastructure.system.ignore_service import IgnoreService
from services.infrastructure.system.diagnostic_service import DiagnosticService
from services.infrastructure.system.process_service import ProcessService
from services.infrastructure.system.validation_service import ValidationService
from services.infrastructure.system.async_task_service import AsyncTaskService
from services.infrastructure.system.search_service import SearchService
from services.infrastructure.system.task_service import TaskService
from services.infrastructure.system.planner_service import PlannerService
from services.infrastructure.system.document_service import DocumentService

# Modular Service Imports - AI & Knowledge
from services.ai import AIService
from services.knowledge import KnowledgeBaseService
from services.knowledge.retrieval.stackoverflow import StackOverflowService

# Windows UTF-8 Enforcement
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

def bootstrap():
    """Build and return the modular FastMCP server."""
    logger = setup_logger("MasterMCP")
    log_startup_banner(logger)
    
    ensure_directories()
    mcp = FastMCP("Master-MCP-Modular")
    
    logger.info("Bootstrap | Initializing Micro-Modular Architecture...")

    # 1. Infrastructure Layer
    bin_svc = BinService(PATHS["PROJECT_ROOT"])
    ignore_svc = IgnoreService(PATHS["default_ignores"], PATHS["PROJECT_ROOT"])
    process_svc = ProcessService(Path(PATHS["SERVER_HOME"]) / ".mcp-master")
    validation_svc = ValidationService()
    
    file_svc = FileSystemService(ALLOWED_ROOTS, ignore_svc, bin_svc, process_svc=process_svc)
    workspace_svc = WorkspaceAnalyzerService(PATHS["PROJECT_ROOT"], ignore_svc)
    search_svc = SearchService()
    task_svc = TaskService(PATHS["tasks"])
    planner_svc = PlannerService()
    doc_svc = DocumentService()

    # 2. AI Layer
    ai_svc = AIService(PATHS["embedding_model"], PATHS["prompts"])
    ai_svc.initialize()
    
    # 3. Knowledge Layer
    knowledge_svc = KnowledgeBaseService(PATHS["local_memory"], PATHS["global_memory"], ai_svc)

    services = {
        "file": file_svc,
        "workspace": workspace_svc,
        "ai": ai_svc,
        "knowledge": knowledge_svc,
        "bin": bin_svc,
        "ignore": ignore_svc,
        "diag": DiagnosticService(ai_svc.ollama, bin_svc),
        "validation": validation_svc,
        "search": search_svc,
        "task": task_svc,
        "planner": planner_svc,
        "doc": doc_svc,
        "stackoverflow": StackOverflowService(STACK_EXCHANGE_API_KEY),
        "process": process_svc,
        "async_task": AsyncTaskService(),
        "logger": logger
    }
    
    # Register process service to the Reaper decorator
    set_process_service_reference(process_svc)

    # Backward compatibility mapping for old tools
    services["llama"] = ai_svc.llama
    services["ollama"] = ai_svc.ollama
    services["memory"] = knowledge_svc
    services["thinking"] = ai_svc.thinking
    services["prompt"] = ai_svc.prompts
    services["validator"] = validation_svc

    # Register All Tools
    from tools import register_all_tools
    register_all_tools(mcp, services, PATHS)
    
    logger.info(f"Bootstrap | Modular Architecture Ready. Project is Lean & Mean.")
    return mcp, logger

if __name__ == "__main__":
    mcp_app, app_logger = bootstrap()
    mcp_app.run()
