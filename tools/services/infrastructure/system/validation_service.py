import json
import yaml
import ast
import subprocess
import tempfile
import os
import xml.etree.ElementTree as ET
from services.core.logger_service import setup_logger
from services.infrastructure.system.bin_service import BinService
from resources.config.settings import PATHS
from typing import Tuple, Optional
from pathlib import Path

logger = setup_logger("ValidationService")

class ValidationService:
    """Service to validate syntax of various file formats using high-performance tools."""
    
    def __init__(self):
        # Go up 3 levels from services/infrastructure/system/
        self.project_root = Path(__file__).parents[3].resolve()
        self.bin_service = BinService(self.project_root)
        logger.info("ValidationService initialized with BinService.")

    def _run_tool(self, tool_name: str, args: list) -> Tuple[int, str, str]:
        """Generic helper to run a tool via BinService."""
        tool_path = self.bin_service.get_binary_path(tool_name)
        if not tool_path:
            return -1, "", f"Tool {tool_name} not found in bin/ or PATH."
            
        cmd = [str(tool_path)] + args
        try:
            # Use shell=True on Windows for consistency with previous implementation
            is_win = os.name == 'nt'
            result = subprocess.run(cmd, capture_output=True, text=True, shell=is_win)
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            logger.error(f"Error running {tool_name}: {e}")
            return -1, "", str(e)

    def _validate_js_ts(self, content: str, ext: str, file_path: Optional[str] = None) -> Tuple[bool, str]:
        """Validate JS/TS using Oxlint (primary) or Biome (fallback)."""
        temp_path = None
        if not file_path:
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False, mode='w', encoding='utf-8') as tf:
                tf.write(content)
                temp_path = tf.name
        
        target_path = file_path or temp_path

        try:
            # Try Oxlint first
            rc, stdout, stderr = self._run_tool("oxlint", ["-D", "correctness", "--format", "json", target_path])
            
            if rc != -1 and stdout:
                try:
                    data = json.loads(stdout)
                    diagnostics = data.get("diagnostics", [])
                    if not diagnostics:
                        return True, "SYNTAX OK (Oxlint)"
                    
                    err = diagnostics[0]
                    msg = f"[Oxlint: {err.get('code')}] {err.get('message')}"
                    return False, msg
                except:
                    pass

            # Fallback to Biome if available
            rc, stdout, stderr = self._run_tool("biome", ["lint", "--format", "json", target_path])
            if rc != -1:
                if rc == 0:
                    return True, "SYNTAX OK (Biome)"
                return False, f"Biome detected errors. {stderr[:100]}"

            return False, "Validation tools (oxlint/biome) failed or not found."
            
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def _validate_python_ruff(self, content: str, file_path: Optional[str] = None) -> Tuple[bool, str]:
        """Validate Python using Ruff (beyond simple ast.parse)."""
        temp_path = None
        if not file_path:
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode='w', encoding='utf-8') as tf:
                tf.write(content)
                temp_path = tf.name
        
        target_path = file_path or temp_path

        try:
            # ruff check --output-format json --cache-dir <central_path> <path>
            cache_dir = os.path.join(PATHS["GLOBAL_DATA"], "cache", "ruff")
            rc, stdout, stderr = self._run_tool("ruff", [
                "check", 
                "--output-format", "json", 
                "--cache-dir", cache_dir,
                target_path
            ])
            
            if rc == -1:
                # If ruff not found, fallback to standard ast.parse
                if content:
                    ast.parse(content)
                else:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        ast.parse(f.read())
                return True, "SYNTAX OK (AST fallback)"

            if rc == 0:
                return True, "SYNTAX OK (Ruff)"
                
            try:
                data = json.loads(stdout)
                if not data:
                    return True, "SYNTAX OK (Ruff empty)"
                
                err = data[0]
                msg = f"[Ruff: {err.get('code')}] {err.get('message')} at line {err.get('location', {}).get('row')}"
                return False, msg
            except Exception as pe:
                return False, f"Ruff found errors but output parse failed: {str(pe)}"

        except Exception as e:
            return False, str(e)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def validate(self, content: Optional[str] = None, ext: Optional[str] = None, file_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate content or file based on extension.
        Returns (is_valid, message).
        """
        if file_path:
            ext = Path(file_path).suffix.lower().strip('.')
            if not content:
                # If no content provided, we'll read for local-only validators (json, yaml)
                # But for tools like Ruff/Oxlint, we use the path directly.
                pass
        elif ext:
            ext = ext.lower().strip('.')
        else:
            return False, "Either file_path or extension (with content) must be provided."

        logger.info(f"validate() | ext=.{ext} | file_path={file_path} | has_content={bool(content)}")

        try:
            # Tool-based validators (don't necessarily need to read content here)
            if ext == "py":
                return self._validate_python_ruff(content, file_path)
            elif ext in ["js", "mjs", "cjs", "ts", "mts", "cts"]:
                return self._validate_js_ts(content, ext, file_path)

            # Manual string-based validators (need content)
            if not content and file_path:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            if not content:
                return False, "Content is empty for format requiring content-based validation."

            if ext == "json":
                json.loads(content)
            elif ext in ["yaml", "yml"]:
                yaml.safe_load(content)
            elif ext == "xml":
                ET.fromstring(content)
            else:
                logger.warning(f"validate() | Unsupported extension: .{ext}")
                return False, f"Unsupported extension: {ext}"
            
            logger.info(f"validate() | PASS | ext=.{ext}")
            return True, "SYNTAX OK"

        except Exception as e:
            logger.warning(f"validate() | FAIL | ext=.{ext} | error={str(e)}")
            return False, str(e)
