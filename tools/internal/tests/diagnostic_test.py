import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from services.ai.ollama_service import OllamaService
from services.core.bin_service import BinService
from services.core.diagnostic_service import DiagnosticService

async def test_diagnostics():
    print("--- Diagnostic Service Test (Simulation Mode) ---")
    
    ollama_svc = OllamaService()
    bin_svc = BinService(PROJECT_ROOT)
    diag_svc = DiagnosticService(ollama_svc, bin_svc)
    
    # 1. Normal State (assuming system is okay, but let's just check)
    report = await diag_svc.get_health_report(force_refresh=True)
    print(f"Initial Health: {report['components']['ollama']['status']}")
    
    # 2. Simulate Ollama Failure
    print("\nSimulating Ollama failure...")
    diag_svc.simulate_failure("ollama")
    
    report_fail = await diag_svc.get_health_report(force_refresh=True)
    print(f"Health after simulation: {report_fail['components']['ollama']['status']}")
    
    # 3. Check Tool Dependency (Degraded Mode)
    print("\nChecking 'ask_expert' dependency during failure...")
    err = await diag_svc.check_tool_dependency("ask_expert")
    print(f"Result for ask_expert: {err}")
    
    if err and "unreachable" in err:
        print("SUCCESS: Degraded Mode error message received.")
    else:
        print("FAILURE: Expected error message not received.")

    # 4. Check 'memory_store_fact' (Warning vs Error)
    print("\nChecking 'memory_store_fact' dependency during failure...")
    err_mem = await diag_svc.check_tool_dependency("memory_store_fact")
    print(f"Result for memory_store_fact: {err_mem}")

    # 5. Simulate Binary Failure
    print("\nSimulating 'rg' (ripgrep) failure...")
    diag_svc.simulate_failure("rg")
    err_rg = await diag_svc.check_tool_dependency("search_files")
    print(f"Result for search_files: {err_rg}")

    if "rg" in err_rg:
        print("SUCCESS: Binary failure detected accurately.")

if __name__ == "__main__":
    asyncio.run(test_diagnostics())
