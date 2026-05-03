import os
import shutil
import pathlib
from typing import List, Dict, Any, Optional

class IOManager:
    """Handles basic disk I/O operations."""
    
    @staticmethod
    def list_directory(target_dir: str) -> List[Dict[str, Any]]:
        items = []
        for name in os.listdir(target_dir):
            path = os.path.join(target_dir, name)
            items.append({
                "name": name,
                "is_dir": os.path.isdir(path),
                "size": os.path.getsize(path) if os.path.isfile(path) else 0
            })
        return items

    @staticmethod
    def create_directory(directory: str):
        os.makedirs(directory, exist_ok=True)

    @staticmethod
    def write_file(file_path: str, content: str, encoding: str = 'utf-8'):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)

    @staticmethod
    def move_item(source: str, dest: str) -> str:
        shutil.move(source, dest)
        return f"Moved {source} to {dest}"

    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        stat = os.stat(file_path)
        return {
            "path": file_path,
            "name": os.path.basename(file_path),
            "size": stat.st_size,
            "is_dir": os.path.isdir(file_path),
            "mtime": stat.st_mtime
        }
        
    @staticmethod
    def is_binary(file_path: str) -> bool:
        """Check for null bytes in the first 2KB of the file."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(2048)
                return b'\x00' in chunk
        except:
            return False
