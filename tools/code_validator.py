"""
Code syntax validator for the agent system.
Extracted and simplified from Master-MCP (tools/services/infrastructure/system/validation_service.py).

Provides:
  - validate_code(code, extension) -> (is_valid, message)
  - extract_code_blocks(text)      -> list of (code, ext) tuples
  - validate_agent_output(text)    -> formatted validation report string

Priority: ruff (Python) > ast.parse fallback > no-op for unsupported extensions.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
import os
from typing import Tuple, List


# ---------------------------------------------------------------------------
# Per-language validators
# ---------------------------------------------------------------------------

def _validate_python(code: str) -> Tuple[bool, str]:
    """Try ruff first; fall back to ast.parse."""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(code)
            tmp = f.name

        result = subprocess.run(
            ["ruff", "check", "--output-format", "json", tmp],
            capture_output=True, text=True, timeout=15,
        )
        os.unlink(tmp)

        if result.returncode == 0:
            return True, "SYNTAX OK (ruff)"

        try:
            errors = json.loads(result.stdout)
            if errors:
                e = errors[0]
                loc  = e.get("location", {})
                code_ = e.get("code", "?")
                msg   = e.get("message", "unknown error")
                line  = loc.get("row", "?")
                return False, f"[ruff {code_}] {msg} — line {line}"
        except Exception:
            pass
        return False, "ruff: syntax errors found"

    except (FileNotFoundError, subprocess.TimeoutExpired):
        # ruff not installed — fall back to ast
        pass
    except Exception:
        pass

    try:
        ast.parse(code)
        return True, "SYNTAX OK (ast)"
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"


def _validate_json(content: str) -> Tuple[bool, str]:
    try:
        json.loads(content)
        return True, "SYNTAX OK (json)"
    except json.JSONDecodeError as e:
        return False, f"JSONDecodeError: {e}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_code(code: str, extension: str = "py") -> Tuple[bool, str]:
    """
    Validate a code snippet by its file extension.
    Returns (is_valid: bool, message: str).
    Unsupported extensions are treated as valid (no-op).
    """
    ext = extension.lower().lstrip(".")
    if not code.strip():
        return True, "empty — skipped"

    if ext == "py":
        return _validate_python(code)
    if ext == "json":
        return _validate_json(content=code)
    # HTML, CSS, JS — no local validator, treat as valid
    return True, f"no validator for .{ext} — skipped"


def extract_code_blocks(text: str) -> List[Tuple[str, str]]:
    """
    Extract all fenced code blocks from markdown-style text.
    Returns list of (code_content, extension) tuples.
    Extension defaults to 'py' when not specified.
    """
    pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    blocks: List[Tuple[str, str]] = []
    for m in pattern.finditer(text):
        lang = (m.group(1) or "py").lower()
        code = m.group(2)
        blocks.append((code, lang))
    return blocks


def validate_agent_output(text: str) -> str:
    """
    Scan all code blocks in the agent output and return a
    human-readable validation report.  Returns '' if no code found.
    """
    blocks = extract_code_blocks(text)
    if not blocks:
        return ""

    results: List[str] = []
    for i, (code, ext) in enumerate(blocks, 1):
        ok, msg = validate_code(code, ext)
        status = "✅" if ok else "❌"
        results.append(f"{status} Block {i} (.{ext}): {msg}")

    return "[SYNTAX VALIDATION]\n" + "\n".join(results)
