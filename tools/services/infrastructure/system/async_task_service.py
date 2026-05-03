import asyncio
import uuid
import time
from typing import Dict, Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("AsyncTaskService")

class AsyncTaskService:
    """
    Manages background Python coroutines.
    Similar to ProcessService but for internal async tasks.
    """
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}

    def run_task(self, coro_or_func, name: str) -> str:
        """
        Starts a coroutine in background and returns task_id.
        coro_or_func: Either a coroutine object or a function that returns a coroutine when called with task_id.
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        
        self.tasks[task_id] = {
            "name": name,
            "status": "running",
            "start_time": time.time(),
            "result": None,
            "error": None,
            "progress": 0,  # 0 to 100
            "eta": None
        }

        # If it's a function (factory), call it with the task_id
        if callable(coro_or_func):
            coro = coro_or_func(task_id)
        else:
            coro = coro_or_func

        # Create the wrapper to capture result/error
        async def task_wrapper():
            try:
                result = await coro
                if task_id in self.tasks:
                    self.tasks[task_id]["status"] = "completed"
                    self.tasks[task_id]["result"] = result
                    logger.info(f"Background task [{task_id}] ({name}) completed successfully.")
            except Exception as e:
                if task_id in self.tasks:
                    self.tasks[task_id]["status"] = "error"
                    self.tasks[task_id]["error"] = str(e)
                    logger.error(f"Background task [{task_id}] ({name}) failed: {e}")

        asyncio.create_task(task_wrapper())
        logger.info(f"Started background task [{task_id}] ({name})")
        return task_id

    def get_status(self, task_id: str) -> Dict[str, Any]:
        """Returns the current state of a task."""
        if task_id not in self.tasks:
            return {"status": "not_found"}
        
        task_info = self.tasks[task_id].copy()
        # Add duration
        if task_info["status"] == "running":
            task_info["duration_sec"] = round(time.time() - task_info["start_time"], 1)
        
        return task_info

    def update_progress(self, task_id: str, progress: int, eta: Optional[str] = None):
        """Allows internal functions to report progress."""
        if task_id in self.tasks:
            self.tasks[task_id]["progress"] = progress
            if eta:
                self.tasks[task_id]["eta"] = eta

    def list_tasks(self) -> Dict[str, Any]:
        """Lists all recorded tasks."""
        return self.tasks

    def clear_completed(self):
        """Cleanup old tasks."""
        to_delete = [tid for tid, info in self.tasks.items() if info["status"] != "running"]
        for tid in to_delete:
            del self.tasks[tid]
        logger.info(f"Cleared {len(to_delete)} completed background tasks.")
