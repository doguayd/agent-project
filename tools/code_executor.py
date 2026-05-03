"""
Kod Çalıştırıcı
===============
Python kodunu ve pytest testlerini güvenli şekilde yürütür.
GPU devre dışı olsa da kod çalıştırma CPU üzerinden devam eder.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def execute_python(
    code: str,
    timeout: int = 30,
) -> dict[str, object]:
    """
    Python kodunu alt süreçte çalıştır.

    Returns:
        {success, stdout, stderr, returncode}
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return {
            "success":    proc.returncode == 0,
            "stdout":     stdout.decode(errors="replace"),
            "stderr":     stderr.decode(errors="replace"),
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        return {
            "success": False, "stdout": "",
            "stderr":  f"Zaman aşımı ({timeout}s)", "returncode": -1,
        }
    except Exception as exc:
        return {
            "success": False, "stdout": "",
            "stderr":  str(exc), "returncode": -1,
        }


async def run_pytest(
    test_path: str,
    timeout: int = 120,
    extra_args: list[str] | None = None,
) -> dict[str, object]:
    """
    pytest ile test dosyası çalıştır.

    Returns:
        {success, stdout, stderr, passed, failed}
    """
    args = [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"]
    if extra_args:
        args.extend(extra_args)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        out_str = stdout.decode(errors="replace")

        # Sonuç sayısını çıkar
        passed = failed = 0
        for line in out_str.splitlines():
            if "passed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "passed" and i > 0:
                        try:
                            passed = int(parts[i - 1])
                        except ValueError:
                            pass
            if "failed" in line and "error" not in line.lower():
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "failed" and i > 0:
                        try:
                            failed = int(parts[i - 1])
                        except ValueError:
                            pass

        return {
            "success":  proc.returncode == 0,
            "stdout":   out_str,
            "stderr":   stderr.decode(errors="replace"),
            "passed":   passed,
            "failed":   failed,
        }
    except asyncio.TimeoutError:
        return {
            "success": False, "stdout": "",
            "stderr":  f"Test zaman aşımı ({timeout}s)",
            "passed":  0, "failed": 0,
        }
    except Exception as exc:
        return {
            "success": False, "stdout": "",
            "stderr":  str(exc), "passed": 0, "failed": 0,
        }
