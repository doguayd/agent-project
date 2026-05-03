import asyncio
import os
import signal
import subprocess
import time
import uuid
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import deque

import psutil
from services.core.logger_service import setup_logger

logger = setup_logger("ProcessService")

class ProcessService:
    """
    Manages background subprocesses with cross-platform support.
    Features:
    - 3-second hybrid wait logic for immediate feedback.
    - Thread-safe live output buffering.
    - Persistent logs in .mcp-master/logs/processes/.
    - Process tree management using psutil.
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.logs_dir = self.data_dir / "logs" / "processes"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Store active processes: task_id -> {process_obj, start_time, command, log_file, buffer, lock}
        self.active_processes: Dict[str, Dict[str, Any]] = {}
        
        # Store process IDs for each request: request_id -> [pid1, pid2, ...]
        self.request_pids: Dict[str, List[int]] = {}
        self.lock = threading.Lock() # Global lock for safe dict access
        
        logger.info(f"ProcessService initialized. Logs directory: {self.logs_dir}")

    def register_process_to_request(self, pid: int):
        """Links a PID to the current async request context."""
        from utils.decorators import current_request_id
        req_id = current_request_id.get()
        if req_id:
            with self.lock:
                if req_id not in self.request_pids:
                    self.request_pids[req_id] = []
                self.request_pids[req_id].append(pid)
                logger.debug(f"PID {pid} registered to request {req_id}")

    def kill_processes_for_request(self, request_id: str):
        """The Reaper core: Kill all processes associated with a request ID."""
        with self.lock:
            pids = self.request_pids.get(request_id, [])
            if not pids:
                return
            
            logger.info(f"REAPER: Killing {len(pids)} processes for request {request_id}")
            for pid in pids:
                try:
                    proc = psutil.Process(pid)
                    # Kill offspring first
                    for child in proc.children(recursive=True):
                        try: child.kill()
                        except: pass
                    proc.kill()
                    logger.debug(f"Killed PID {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            del self.request_pids[request_id]

    def _read_stream_sync(self, stream, task_id, log_file):
        """Monitor a stream in a separate thread and write to log file + buffer."""
        # Use a local ref to the buffer and lock
        if task_id not in self.active_processes:
            return
        
        info = self.active_processes[task_id]
        buffer = info["buffer"]
        lock = info["lock"]
        
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                # Read line by line for better buffer management
                for line in iter(stream.readline, b''):
                    decoded = line.decode('utf-8', errors='replace')
                    f.write(decoded)
                    f.flush()
                    with lock:
                        buffer.append(decoded)
            stream.close()
        except Exception as e:
            logger.error(f"Error reading stream for task {task_id}: {e}")

    async def run_command(self, command: str, project_root: str) -> Dict[str, Any]:
        """
        Runs a command in the background, waits 3 seconds for initial feedback.
        """
        # Periodic cleanup of old completed tasks
        self.cleanup_stale_tasks()
        
        task_id = f"bg_{uuid.uuid4().hex[:8]}"
        log_file = self.logs_dir / f"{task_id}.log"
        
        logger.info(f"Starting background command [{task_id}]: {command}")
        
        try:
            # Create a subprocess using sync Popen
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Merge stderr into stdout
                cwd=project_root,
                shell=True,
                bufsize=1, # Line buffered
                universal_newlines=False, # Use bytes for the thread reader
                start_new_session=True if os.name != "nt" else False,
            )
            
            # Register PID to current request context for the Reaper
            self.register_process_to_request(process.pid)
            
            self.active_processes[task_id] = {
                "process": process,
                "start_time": time.time(),
                "command": command,
                "log_file": log_file,
                "buffer": deque(maxlen=100),
                "lock": threading.Lock()
            }

            # Start the log monitoring thread
            thread = threading.Thread(
                target=self._read_stream_sync,
                args=(process.stdout, task_id, log_file),
                daemon=True
            )
            thread.start()

            # Hybrid Wait: Poll for 3 seconds
            poll_start = time.time()
            
            while time.time() - poll_start < 3.0:
                if process.poll() is not None:
                    # Process finished early
                    exit_code = process.returncode
                    logger.info(f"Task [{task_id}] finished early with code {exit_code}")
                    
                    with self.active_processes[task_id]["lock"]:
                        output = "".join(list(self.active_processes[task_id]["buffer"]))
                    
                    return {
                        "status": "completed",
                        "task_id": task_id,
                        "output": output,
                        "exit_code": exit_code
                    }
                await asyncio.sleep(0.2)

            # Still running after 3 seconds
            logger.info(f"Task [{task_id}] is still running after 3s. Returning intermediate state.")
            with self.active_processes[task_id]["lock"]:
                output = "".join(list(self.active_processes[task_id]["buffer"]))
                
            return {
                "status": "running",
                "task_id": task_id,
                "output": output,
                "message": "Process is still running in background. Use get_process_status to check progress."
            }

        except Exception as e:
            logger.error(f"Failed to start background command: {e}")
            return {"status": "error", "error": str(e)}

    def get_status(self, task_id: str, tail: int = 50) -> Dict[str, Any]:
        """Reads the status and log output for a task."""
        if task_id not in self.active_processes:
            # Check if log file exists
            log_file = self.logs_dir / f"{task_id}.log"
            if not log_file.exists():
                return {"status": "not_found", "message": f"Task {task_id} not found."}
            
            with open(log_file, "r", encoding="utf-8") as rf:
                lines = rf.readlines()
                output = "".join(lines[-tail:])
            return {"status": "completed", "output": output, "message": "Task history retrieved from logs."}

        task_info = self.active_processes[task_id]
        process = task_info["process"]
        
        # Update status
        exit_code = process.poll()
        is_running = exit_code is None
        
        # Use live buffer for recent output
        with task_info["lock"]:
            output = "".join(list(task_info["buffer"])[-tail:])

        return {
            "status": "running" if is_running else "completed",
            "task_id": task_id,
            "output": output,
            "exit_code": exit_code if not is_running else None
        }

    def stop_task(self, task_id: str) -> Dict[str, Any]:
        """Stops the task and its child processes tree."""
        if task_id not in self.active_processes:
            return {"status": "error", "message": "Task not active or not found."}

        task_info = self.active_processes[task_id]
        process = task_info["process"]
        
        try:
            parent = psutil.Process(process.pid)
            # Terminate children first
            children = parent.children(recursive=True)
            for child in children:
                try: child.terminate()
                except: pass
            
            try: parent.terminate()
            except: pass
            
            # Wait a bit then kill if still alive
            gone, alive = psutil.wait_procs(children + [parent], timeout=3)
            for p in alive:
                try: p.kill()
                except: pass

            logger.info(f"Task [{task_id}] stopped manually.")
            return {"status": "stopped", "task_id": task_id}
        except psutil.NoSuchProcess:
            return {"status": "error", "message": "Process already terminated."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_tasks(self) -> List[Dict[str, Any]]:
        """Lists all tracked processes."""
        summary = []
        for task_id, info in self.active_processes.items():
            exit_code = info["process"].poll()
            summary.append({
                "task_id": task_id,
                "command": info["command"],
                "status": "running" if exit_code is None else "completed",
                "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info["start_time"]))
            })
        return summary

    def cleanup_stale_tasks(self, max_age_seconds: int = 3600):
        """Removes completed tasks older than max_age_seconds from memory."""
        now = time.time()
        tasks_to_remove = []
        for task_id, info in self.active_processes.items():
            exit_code = info["process"].poll()
            if exit_code is not None:
                # Finished. Check age.
                if now - info["start_time"] > max_age_seconds:
                    tasks_to_remove.append(task_id)
        
        for task_id in tasks_to_remove:
            try:
                del self.active_processes[task_id]
                logger.info(f"Cleaned up stale task memory: {task_id}")
            except KeyError:
                pass
