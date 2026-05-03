import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger
from resources.config.settings import resolve_paths

logger = setup_logger("TaskService")

class TaskService:
    """Service to handle internal agent task tracking (State Management)."""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self, file_path: Optional[str] = None):
        """Creates the tasks.json file if it doesn't exist."""
        path = file_path or self.file_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({"tasks": []}, f, indent=2)

    def _get_tasks_path(self, project_root: str) -> str:
        """Get tasks.json path for a given project_root. Mandatory."""
        if not project_root:
            raise ValueError("project_root is mandatory for TaskService.")
        paths = resolve_paths(project_root)
        return paths["tasks"]

    def _read_data(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        path = file_path or self.file_path
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_data(self, data: Dict[str, Any], file_path: Optional[str] = None):
        path = file_path or self.file_path
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def create_plan(self, title: str, project_root: str, execution_plan: List[Dict[str, Any]],
                    problem_analysis: Optional[Dict] = None,
                    best_practices: Optional[List[str]] = None,
                    risk_assessment: Optional[List[str]] = None) -> str:
        """Create a new advanced task plan containing problem analysis and detailed steps."""
        file_path = self._get_tasks_path(project_root)
        self._ensure_file_exists(file_path)
        data = self._read_data(file_path)

        task_id = str(uuid.uuid4())[:8]
        new_task = {
            "id": task_id,
            "title": title,
            "created_at": str(datetime.now()),
            "status": "in_progress",
            "problem_analysis": problem_analysis or {},
            "best_practices": best_practices or [],
            "risk_assessment": risk_assessment or [],
            "steps": []
        }

        for i, step_data in enumerate(execution_plan):
            new_task["steps"].append({
                "index": step_data.get("step", i + 1),
                "action": step_data.get("action", ""),
                "expected_result": step_data.get("expected_result", ""),
                "status": "todo"
            })

        data["tasks"].append(new_task)
        self._write_data(data, file_path)
        logger.info(f"Created advanced task plan: {title} ({task_id})")
        return task_id

    def mark_step(self, task_id: str, step_index: int, status: str, project_root: str) -> str:
        """Update the status of a specific step (todo, in_progress, done)."""
        if status not in ["todo", "in_progress", "done"]:
            return "Error: Status must be 'todo', 'in_progress', or 'done'."

        file_path = self._get_tasks_path(project_root)
        data = self._read_data(file_path)
        for task in data["tasks"]:
            if task["id"] == task_id:
                for step in task["steps"]:
                    if step["index"] == step_index:
                        step["status"] = status

                        # Eğer tüm stepler done ise, taskı done yap
                        if all(s["status"] == "done" for s in task["steps"]):
                            task["status"] = "done"
                        elif any(s["status"] == "in_progress" for s in task["steps"]):
                            task["status"] = "in_progress"

                        self._write_data(data, file_path)
                        return f"Success: Marked task {task_id} step {step_index} as {status}."
                return f"Error: Step {step_index} not found in task {task_id}."

        return f"Error: Task {task_id} not found."

    def get_active_tasks(self, project_root: str) -> List[Dict[ Any]]:
        """Retrieve all non-completed tasks."""
        file_path = self._get_tasks_path(project_root)
        if not os.path.exists(file_path):
            return []
        data = self._read_data(file_path)
        active_tasks = [task for task in data["tasks"] if task["status"] != "done"]
        return active_tasks

    def get_all_tasks(self, project_root: str) -> List[Dict[Any]]:
        """Retrieve all recorded tasks across time."""
        file_path = self._get_tasks_path(project_root)
        if not os.path.exists(file_path):
            return []
        return self._read_data(file_path).get("tasks", [])
