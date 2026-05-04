"""
OSINT Araçları — Sigma için
============================
maigret ile 3000+ sitede kullanıcı adı araması.
Tamamen lokal, API key gerektirmez.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional


async def search_username(
    username:    str,
    max_sites:   int = 100,
    timeout_s:   float = 60.0,
    save_report: bool = True,
    output_dir:  Optional[str] = None,
) -> dict:
    """
    maigret ile kullanıcı adı ara.

    Returns:
        {
          "username": str,
          "found_count": int,
          "sites": [{"site": str, "url": str, "status": str}, ...],
          "report_path": str | None,
          "error": str | None,
        }
    """
    import subprocess
    import shutil

    maigret_cmd = shutil.which("maigret") or _find_maigret()
    if not maigret_cmd:
        return {
            "username":    username,
            "found_count": 0,
            "sites":       [],
            "report_path": None,
            "error":       "maigret bulunamadı. 'pip install maigret' komutunu çalıştırın.",
        }

    # Çıktı dizini
    report_dir = output_dir or str(Path("workspace") / "osint" / username)
    Path(report_dir).mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "maigret",
        username,
        "--json", str(Path(report_dir) / f"{username}.json"),
        "--folderoutput", report_dir,
        "--top-sites", str(max_sites),
        "--no-color",
        "--timeout", "10",
    ]

    result = {
        "username":    username,
        "found_count": 0,
        "sites":       [],
        "report_path": None,
        "error":       None,
    }

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=5,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = b"", b"Timeout"

        # JSON raporu oku
        json_path = Path(report_dir) / f"{username}.json"
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)

            sites = []
            for site_name, info in data.items():
                if isinstance(info, dict):
                    status = info.get("status", {})
                    if isinstance(status, dict):
                        found = status.get("status", "") == "Claimed"
                        url   = info.get("url", "")
                    else:
                        found = False
                        url   = ""
                    if found or url:
                        sites.append({
                            "site":   site_name,
                            "url":    url,
                            "status": "bulundu" if found else "belirsiz",
                        })

            result["sites"]       = sites
            result["found_count"] = len([s for s in sites if s["status"] == "bulundu"])
            result["report_path"] = str(json_path)

        else:
            # stdout'u parse etmeye çalış
            out = stdout.decode("utf-8", errors="replace")
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            found_lines = [l for l in lines if "[+]" in l or "Found" in l]
            result["found_count"] = len(found_lines)
            result["sites"] = [{"site": l, "url": "", "status": "bulundu"} for l in found_lines[:50]]

    except Exception as e:
        result["error"] = str(e)

    return result


def _find_maigret() -> Optional[str]:
    """maigret yürütülebilir dosyasını bul."""
    candidates = [
        Path(sys.executable).parent / "maigret",
        Path(sys.executable).parent / "maigret.exe",
        Path(sys.prefix) / "Scripts" / "maigret.exe",
        Path(sys.prefix) / "bin" / "maigret",
        # Python user path
        Path(os.path.expanduser("~")) / "AppData" / "Roaming" / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts" / "maigret.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


async def search_multiple_usernames(
    usernames: list[str],
    **kwargs,
) -> list[dict]:
    """Birden fazla kullanıcı adını paralel ara."""
    tasks = [search_username(u, **kwargs) for u in usernames]
    return await asyncio.gather(*tasks)
