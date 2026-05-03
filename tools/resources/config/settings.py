import os
import pathlib
import hashlib
import json
from typing import Dict, List, Optional, Any

# --- Core Paths ---
# SERVER_HOME is the directory where main-source resides
# Now that we are in resources/config/settings.py, we need to go up 3 levels
SERVER_HOME = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def find_mcp_root(start_path: str) -> Optional[str]:
    """Recursively searches UP for project markers."""
    current = pathlib.Path(start_path).resolve()
    forbidden = {"AppData", "Program Files", "Windows", "System32", "Temp", "node_modules", ".gemini"}
    
    # --- PHASE 1: Absolute Priority (main.py) ---
    search_ptr = current
    while True:
        if (search_ptr / "main.py").exists():
            return str(search_ptr)
        
        if any(part in search_ptr.parts for part in forbidden):
            break
        parent = search_ptr.parent
        if parent == search_ptr:
            break
        search_ptr = parent

    # --- PHASE 2: Standard Discovery (Fallback) ---
    search_ptr = current
    markers = [".git", "package.json", "pyproject.toml", ".gitignore"]
    while True:
        for marker in markers:
            if (search_ptr / marker).exists():
                return str(search_ptr)
        
        if any(part in search_ptr.parts for part in forbidden):
            break
        parent = search_ptr.parent
        if parent == search_ptr:
            break
        search_ptr = parent
        
    return None

def get_default_root() -> str:
    """Smart root discovery system.
    1. Looks for an explicit .mcp-root marker upward.
    2. Falls back to standard project markers (.git, etc.).
    3. Aborts with error if in a system/forbidden directory.
    """
    cwd = os.getcwd()
    
    # Priority 1: Recursive Marker Discovery
    detected_root = find_mcp_root(cwd)
    if detected_root:
        return detected_root
        
    # Priority 2: Standard fallback (one level up if inside server)
    if cwd.lower() == SERVER_HOME.lower():
        return os.path.dirname(SERVER_HOME)
        
    # Priority 3: Safety Guard
    forbidden = ["AppData", "Program Files", "System32", "Temp"]
    if any(p.lower() in cwd.lower() for p in forbidden):
        # Instead of failing silently or guessing, return a safe path or raise
        # For this server, we'll default to the parent of the server home
        return os.path.dirname(SERVER_HOME)
        
    return cwd

PROJECT_ROOT = os.getenv("PROJECT_ROOT", get_default_root())

# --- Centralized Storage Config ---
GLOBAL_DATA_DIR = os.getenv("MCP_MASTER_DATA_DIR", os.path.join(os.path.expanduser("~"), ".mcp-master"))

def get_project_id(path: str) -> str:
    """Generate a readable path-based slug for the current project.
    Example: C:/Users/akbas/Mcp -> c--Users-akbas-Mcp
    """
    try:
        abs_path = str(pathlib.Path(path).resolve())
    except:
        abs_path = os.path.abspath(path)
        
    # Remove leading/trailing slashes and handle drive colon
    slug = abs_path.replace(':\\', '--').replace(':/', '--').replace('\\', '-').replace('/', '-')
    
    # Clean up multiple dashes if any
    while '--' in slug and '---' in slug: # only collapse if > 2
        slug = slug.replace('---', '--')
        
    return slug

PROJECT_ID = get_project_id(PROJECT_ROOT)
LOCAL_DATA_DIR = os.path.join(GLOBAL_DATA_DIR, "projects", PROJECT_ID)

# --- Centralized Projects Registry ---
PROJECT_REGISTRY_FILE = os.path.join(GLOBAL_DATA_DIR, "projects", "memory.json")

def load_project_registry() -> List[Dict[str, str]]:
    """Load the list of all indexed projects."""
    if not os.path.exists(PROJECT_REGISTRY_FILE):
        return []
    try:
        with open(PROJECT_REGISTRY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("projects", [])
    except Exception:
        return []

def save_to_registry(project_root: str, project_id: str, metadata: Optional[Dict[str, Any]] = None):
    """Register or update a project in the central memory.json with metadata support."""
    registry = load_project_registry()
    abs_path = str(pathlib.Path(project_root).resolve())
    
    # Update if exists, or append
    updated = False
    for p in registry:
        if p["path"].lower() == abs_path.lower():
            p["id"] = project_id
            if metadata:
                if "metadata" not in p: p["metadata"] = {}
                p["metadata"].update(metadata)
            updated = True
            break
            
    if not updated:
        entry = {"path": abs_path, "id": project_id}
        if metadata:
            entry["metadata"] = metadata
        registry.append(entry)
        
    os.makedirs(os.path.dirname(PROJECT_REGISTRY_FILE), exist_ok=True)
    with open(PROJECT_REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"projects": registry}, f, indent=2)

def get_project_entry(project_root: str) -> Optional[Dict[str, Any]]:
    """Helper to get the full registry entry for a project."""
    registry = load_project_registry()
    abs_path = str(pathlib.Path(project_root).resolve()).lower()
    for p in registry:
        if p["path"].lower() == abs_path:
            return p
    return None

def resolve_best_project_context(target_path: str) -> Optional[Dict[str, str]]:
    """
    Find the best matching indexed project for a given path.
    Checks for exact match first, then checks parents.
    """
    registry = load_project_registry()
    target_abs = str(pathlib.Path(target_path).resolve()).lower()
    
    best_match = None
    max_len = -1
    
    for p in registry:
        p_path = p["path"].lower()
        # Check if target_abs is p_path or a sub-path of p_path
        if target_abs == p_path or target_abs.startswith(p_path + os.sep):
            # We want the 'longest' path that matches (deepest root)
            if len(p_path) > max_len:
                max_len = len(p_path)
                best_match = p
                
    return best_match

# --- Access Control ---
ALLOWED_ROOTS: List[str] = [
    str(pathlib.Path(PROJECT_ROOT).resolve()),
    str(pathlib.Path(SERVER_HOME).resolve()),
    str(pathlib.Path.home().resolve()),
]

# Additional roots can be added via environment variable
extra_roots = os.getenv("ADDITIONAL_ROOTS", "")
if extra_roots:
    ALLOWED_ROOTS.extend([str(pathlib.Path(p.strip()).resolve()) for p in extra_roots.split(",")])

# --- Data & Service Paths ---
def build_paths(project_root: str, project_id: str) -> Dict[str, str]:
    """Build PATHS dict for a given project."""
    local_data_dir = os.path.join(GLOBAL_DATA_DIR, "projects", project_id)
    return {
        "SERVER_HOME": SERVER_HOME,
        "PROJECT_ROOT": project_root,
        "GLOBAL_DATA": GLOBAL_DATA_DIR,
        "LOCAL_DATA": local_data_dir,
        "prompts": os.path.join(SERVER_HOME, "resources", "prompts"),
        "local_memory": os.path.join(local_data_dir, "memory"),
        "global_memory": os.path.join(GLOBAL_DATA_DIR, "global", "memory"),
        "memory": os.path.join(local_data_dir, "memory"),
        "tasks": os.path.join(local_data_dir, "tasks.json"),
        "audit_logs": os.path.join(GLOBAL_DATA_DIR, "global", "audit_logs"),
        "requirements": os.path.join(SERVER_HOME, "requirements.txt"),
        "default_ignores": os.path.join(SERVER_HOME, "resources", "config", "default_ignores.txt"),
        "models": os.path.join(SERVER_HOME, "resources", "models"),
        "embedding_model": os.path.join(SERVER_HOME, "resources", "models", "paraphrase-multilingual-MiniLM-L12-118M-v2-Q8_0.gguf"),
    }

PATHS: Dict[str, str] = build_paths(PROJECT_ROOT, PROJECT_ID)

def resolve_paths(project_root: str) -> Dict[str, str]:
    """
    Get paths for a specific project_root.
    This is the core for dynamic, multi-project support.
    """
    if not project_root:
        raise ValueError("project_root is mandatory for dynamic path resolution.")
        
    project_id = get_project_id(project_root)
    return build_paths(project_root, project_id)

# --- Service Settings ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")
MAX_INDEX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
STACK_EXCHANGE_API_KEY = os.getenv("STACK_EXCHANGE_API_KEY")

# --- Directory Initialization ---
def ensure_directories(paths: Dict[str, str] | None = None):
    """Ensure that all necessary data directories exist."""
    if paths is None:
        paths = PATHS
    required_dirs = [
        paths["local_memory"],
        paths["global_memory"],
        paths["audit_logs"]
    ]
    for d in required_dirs:
        os.makedirs(d, exist_ok=True)
    
    # Initialize projects registry if missing
    if not os.path.exists(PROJECT_REGISTRY_FILE):
        os.makedirs(os.path.dirname(PROJECT_REGISTRY_FILE), exist_ok=True)
        with open(PROJECT_REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump({"projects": []}, f, indent=2)
