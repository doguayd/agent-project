import os
import pathlib
from typing import List

RESTRICTED_PATHS = {
    "windows": [
        "C:\\Windows", "C:\\Windows\\System32",
        "C:\\Program Files", "C:\\Program Files (x86)",
        "C:\\ProgramData"
    ],
    "linux": [
        "/etc", "/root", "/boot", "/dev", "/proc", "/sys", "/run"
    ]
}

def is_path_restricted(path: str) -> bool:
    """Check if the path falls under restricted system directories."""
    norm_path = os.path.normpath(path).lower()
    
    # Check Windows restrictions
    for rest in RESTRICTED_PATHS["windows"]:
        norm_rest = os.path.normpath(rest).lower()
        if norm_path == norm_rest or norm_path.startswith(norm_rest + os.sep):
            return True
            
    # Check Linux restrictions
    for rest in RESTRICTED_PATHS["linux"]:
        if norm_path == rest or norm_path.startswith(norm_path + "/"):
            return True
            
    return False

class SecurityManager:
    """Handles path resolution and safety boundary checks."""
    def __init__(self, allowed_roots: List[str]):
        self.allowed_roots = [pathlib.Path(p).resolve() for p in allowed_roots]

    def resolve_path(self, target_path: str) -> str:
        """Resolve path and verify it is within one of the allowed roots."""
        try:
            p = pathlib.Path(target_path)
            if not p.is_absolute():
                p = self.allowed_roots[0] / target_path
            
            abs_path = p.resolve()
            str_path = str(abs_path)
            
            if is_path_restricted(str_path):
                raise PermissionError(f"Access Denied: '{target_path}' is a restricted system path.")

            for root in self.allowed_roots:
                if abs_path == root or abs_path.is_relative_to(root):
                    return str(abs_path)
            
            allowed_str = ", ".join([str(r) for r in self.allowed_roots])
            raise PermissionError(
                f"Access denied: '{target_path}' outside allowed roots.\nAllowed: {allowed_str}"
            )
        except Exception as e:
            if isinstance(e, PermissionError): raise
            raise ValueError(f"Invalid path: {target_path}. Error: {str(e)}")
