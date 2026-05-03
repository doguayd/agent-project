import asyncio
import os
import sys

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from resources.config.settings import PATHS, ensure_directories
from services.core.file_service import FileService
from services.orchestration.planner_service import PlannerService
from services.core.validation_service import ValidationService

async def main():
    print("Starting Master MCP Smoke Test (Modular Architecture)...\n")
    
    # Initialize Environment
    ensure_directories()
    
    # Initialize Services
    file_svc = FileService([PATHS["PROJECT_ROOT"]])
    planner_svc = PlannerService()
    validator_svc = ValidationService()

    # 1. Test Config & Paths
    print("--- Testing Config Layer ---")
    print(f"PROJECT_ROOT: {PATHS['PROJECT_ROOT']}")
    print(f"Memory Path: {PATHS['memory']}\n")

    # 2. Test File Services (including read_multiple fix)
    print("--- Testing File Service ---")
    test_file = os.path.join(PATHS["PROJECT_ROOT"], "temp_smoke_test.txt")
    file_svc.write_file("temp_smoke_test.txt", "Hello World")
    
    files = file_svc.read_multiple(["temp_smoke_test.txt"])
    if files.get("temp_smoke_test.txt") == "Hello World":
        print("Read Multiple Check: Passed")
    else:
        print(f"Read Multiple Check: Failed (Content: {files.get('temp_smoke_test.txt')})")
    
    os.remove(test_file)
    print("File Cleanup: Done\n")

    # 3. Test Validation Service
    print("--- Testing Syntax Guardian ---")
    bad_json = '{"key": "value",}' # Trailing comma
    is_valid, msg = validator_svc.validate(bad_json, "json")
    print(f"Bad JSON Check: {'Passed' if not is_valid else 'Failed'} (Error: {msg})")
    
    good_py = "def hello():\n    return 'world'"
    is_valid, msg = validator_svc.validate(good_py, "py")
    print(f"Good Python Check: {'Passed' if is_valid else 'Failed'}\n")

    # 4. Test Planner Service
    print("--- Testing Planner Service (Pure Logic) ---")
    goal = "Build a modular system"
    ok, msg, structured = planner_svc.structure_plan(
        goal=goal,
        execution_plan=[{"step": 1, "action": "Refactor", "expected_result": "Clean code"}],
        problem_analysis={"core_problem": "Spaghetti code"}
    )
    
    if ok:
        print(f"Plan Structured OK: {structured['goal']}\n")
    else:
        print(f"Planner Test Failed: {msg}\n")

    print("Smoke Test Completed Successfully!")

if __name__ == "__main__":
    asyncio.run(main())
