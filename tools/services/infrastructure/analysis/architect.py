from typing import List, Dict, Any

class Architect:
    """Infers architectural roles and guesses project structure."""
    
    @staticmethod
    def infer_roles(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        roles = []
        for f in files:
            path = f["path"].lower()
            role = "logic"
            if "main.py" in path or "app.py" in path: role = "entrypoint"
            elif "services/" in path: role = "service"
            elif "models/" in path: role = "model"
            elif "tests/" in path or "test_" in path: role = "test"
            elif "config" in path: role = "config"
            
            roles.append({"path": f["path"], "role": role})
        return roles

    @staticmethod
    def guess_architecture(files: List[Dict[str, Any]]) -> str:
        paths = [f["path"].lower() for f in files]
        if any("services/" in p for p in paths) and any("models/" in p for p in paths):
            return "Layered (Service-Model)"
        if any("app/" in p for p in paths) and any("index." in p for p in paths):
            return "Modular Web"
        return "Script-based / Monolithic"
