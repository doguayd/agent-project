import os
import sys
import platform
from pathlib import Path

def get_platform_info():
    os_name = sys.platform
    machine = platform.machine().lower()
    if "64" in machine:
        arch = "x64"
    else:
        arch = "x86"
    return f"{os_name}/{arch}"

def check_binaries():
    plat = get_platform_info()
    print(f"--- Versatile MCP Binary Health Check ---")
    print(f"Detected Platform: {plat}\n")
    
    project_root = Path(__file__).parent.parent
    bin_dir = project_root / "bin" / plat
    
    required_tools = ["ruff", "biome", "oxlint", "rg"]
    found_all = True
    
    if "win32" in plat:
        print("[*] Checking bundled Windows binaries...")
        for tool in required_tools:
            ext = ".exe"
            path = bin_dir / f"{tool}{ext}"
            if path.exists():
                print(f"  [OK] {tool:10} found at {path.name}")
            else:
                print(f"  [!!] {tool:10} MISSING!")
                found_all = False
        
        if found_all:
            print("\n[SUCCESS] All Windows binaries are present and ready to go.")
        else:
            print("\n[WARNING] Some binaries are missing. Please ensure you downloaded the full repository.")
    else:
        print("[!] Native binaries are not bundled for Linux/macOS.")
        print("[*] Please install them manually using your package manager:")
        print("    - ripgrep (rg): sudo apt install ripgrep")
        print("    - ruff: pip install ruff")
        print("    - biome: npm install -g @biomejs/biome")

if __name__ == "__main__":
    check_binaries()
