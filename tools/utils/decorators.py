import asyncio
import functools
import contextvars
import uuid
from typing import Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("TimeoutDecorator")

# Global context for tracking the current request
current_request_id = contextvars.ContextVar("current_request_id", default=None)

# Global reference to ProcessService for the Reaper to use
_process_service_ref = None

def set_process_service_reference(svc: Any):
    """Sets the global process service reference for the timeout decorator."""
    global _process_service_ref
    _process_service_ref = svc

def mcp_timeout(seconds: int = 60):
    """
    Advanced decorator to enforce a timeout on async MCP tool functions.
    If the tool takes longer than `seconds`, it is aborted AND its 
    child processes are killed.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            req_id = f"req_{uuid.uuid4().hex[:6]}"
            token = current_request_id.set(req_id)
            
            logger.debug(f"Tool '{func.__name__}' [ID: {req_id}] starting with {seconds}s timeout.")
            
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                logger.error(f"Tool '{func.__name__}' [ID: {req_id}] TIMED OUT. Triggering REAPER.")
                if _process_service_ref:
                    _process_service_ref.kill_processes_for_request(req_id)
                return f"FAILURE: Tool execution timed out after {seconds} seconds. Operation aborted and processes killed to prevent system hang."
            except Exception as e:
                logger.error(f"Error in tool '{func.__name__}' [ID: {req_id}]: {str(e)}")
                raise e
            finally:
                current_request_id.reset(token)
        return wrapper
    return decorator
