import os
from typing import List, Optional
import pathspec
from services.core.logger_service import setup_logger

logger = setup_logger("IgnoreService")

class IgnoreService:
    """Service to handle file/directory ignore patterns using .gitignore syntax."""
    
    def __init__(self, default_ignore_path: str, project_root: str):
        self.default_ignore_path = default_ignore_path
        self.project_root = project_root
        self.spec: Optional[pathspec.PathSpec] = None
        self._load_patterns()

    def _load_patterns(self):
        """Load patterns from default file and ALL .gitignore files in the project."""
        all_patterns = []
        
        # 1. Load forced system ignores
        all_patterns.extend([
            ".git/",
            ".mcp-master/",
            "__pycache__/",
            "*.pyc"
        ])

        # 2. Load default global ignore file (system baseline)
        if os.path.exists(self.default_ignore_path):
            try:
                with open(self.default_ignore_path, 'r', encoding='utf-8') as f:
                    all_patterns.extend(f.readlines())
                logger.debug(f"Loaded default ignore patterns from {self.default_ignore_path}")
            except Exception as e:
                logger.error(f"Failed to load default ignores: {e}")

        # 3. Dynamic Multi-Gitignore Discovery
        # Scans for all .gitignore files in the project hierarchy
        try:
            for root, dirs, files in os.walk(self.project_root, topdown=True):
                # Optimization: skip known massive ignored folders during search
                dirs[:] = [d for d in dirs if d not in [".git", "node_modules", ".venv", "venv", "dist", "build"]]
                
                if ".gitignore" in files:
                    g_path = os.path.join(root, ".gitignore")
                    rel_dir = os.path.relpath(root, self.project_root).replace("\\", "/")
                    prefix = "" if rel_dir == "." else f"{rel_dir}/"
                    
                    try:
                        with open(g_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith('#'):
                                    # Adjust pattern to be relative to projected root
                                    # If pattern starts with /, it's relative to the gitignore dir
                                    # We prepend the relative directory path to scope it correctly
                                    adjusted = f"{prefix}{line}"
                                    all_patterns.append(adjusted)
                        logger.info(f"Integrated patterns from {prefix}.gitignore")
                    except Exception as e:
                        logger.error(f"Failed to load {g_path}: {e}")
        except Exception as e:
            logger.error(f"Error during .gitignore discovery: {e}")

        # 4. Filter empty lines and comments
        clean_patterns = [
            line.strip() for line in all_patterns 
            if line.strip() and not line.strip().startswith('#')
        ]

        self.spec = pathspec.PathSpec.from_lines('gitwildmatch', clean_patterns)
        logger.info(f"IgnoreService initialized with {len(clean_patterns)} combined patterns.")

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """
        Check if a relative path (from project root) matches any ignore pattern.
        """
        if not self.spec:
            return False
            
        # Normalize path for pathspec
        normalized_path = rel_path.replace("\\", "/")
        
        # Git patterns often require a trailing slash for directory matches
        if is_dir and not normalized_path.endswith("/"):
            normalized_path += "/"
            
        return self.spec.match_file(normalized_path)

    def refresh(self):
        """Reload patterns from files."""
        self._load_patterns()
