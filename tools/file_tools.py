"""
Dosya Araçları
==============
Çalışma alanı (workspace/) içinde güvenli dosya okuma/yazma.
Coder çıktısından otomatik dosya çıkarma (extract_code_files).
"""

from __future__ import annotations

import re
from pathlib import Path

import aiofiles

from config import WORKSPACE_DIR


def _workspace_path(filename: str, project: str = "") -> Path:
    base = Path(WORKSPACE_DIR) / project if project else Path(WORKSPACE_DIR)
    p = base / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def read_file(path: str, workspace: bool = True, project: str = "") -> str:
    """Dosya içeriğini oku. workspace=True ise WORKSPACE_DIR'e göre."""
    full = _workspace_path(path, project) if workspace else Path(path)
    if not full.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {full}")
    async with aiofiles.open(full, encoding="utf-8") as f:
        return await f.read()


async def write_file(
    filename: str,
    content: str,
    workspace: bool = True,
    project: str = "",
) -> str:
    """
    Dosyaya içerik yaz.
    Returns: Yazılan dosyanın tam yolu.
    """
    full = _workspace_path(filename, project) if workspace else Path(filename)
    if not workspace:
        full.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(full, "w", encoding="utf-8") as f:
        await f.write(content)

    return str(full)


async def list_workspace_files(subdir: str = "") -> list[str]:
    """Çalışma alanındaki tüm dosyaları listele."""
    base = Path(WORKSPACE_DIR) / subdir if subdir else Path(WORKSPACE_DIR)
    if not base.exists():
        return []
    return [
        str(f.relative_to(Path(WORKSPACE_DIR)))
        for f in base.rglob("*")
        if f.is_file()
    ]


# ─── Kod dosyası çıkarma ──────────────────────────────────────────────────────

# Desteklenen uzantılar ve varsayılan isimlendirme
_EXT_DEFAULTS: dict[str, str] = {
    "html":       "index.html",
    "css":        "styles.css",
    "javascript": "script.js",
    "js":         "script.js",
    "python":     "main.py",
    "py":         "main.py",
    "typescript": "main.ts",
    "ts":         "main.ts",
    "json":       "data.json",
    "sql":        "schema.sql",
    "sh":         "run.sh",
    "bash":       "run.sh",
    "yaml":       "config.yaml",
    "yml":        "config.yaml",
    "toml":       "config.toml",
    "md":         "README.md",
    "txt":        "output.txt",
}


def extract_code_files(text: str) -> list[tuple[str, str]]:
    """
    Coder çıktısından dosya ismi + içerik çiftlerini çıkarır.

    Desteklenen formatlar:
      1. ### filename.ext ###  (veya ### filename.ext)
         ```lang
         ...
         ```
      2. Sadece ```lang ... ``` blokları (dosya ismi dil uzantısından türetilir)

    Returns: [(filename, content), ...]
    """
    files: list[tuple[str, str]] = []
    seen_names: dict[str, int] = {}

    def _unique_name(name: str) -> str:
        if name not in seen_names:
            seen_names[name] = 0
            return name
        seen_names[name] += 1
        stem = Path(name).stem
        ext  = Path(name).suffix
        return f"{stem}_{seen_names[name]}{ext}"

    # Pattern 1: ### filename.ext ### + code block
    pat1 = re.compile(
        r'###\s*([\w.\-/]+\.[\w]+)\s*(?:###)?\s*\n```[\w]*\n(.*?)```',
        re.DOTALL
    )
    # Pattern 1b: ### filename ### without extension in header, lang in fence
    pat1b = re.compile(
        r'###\s*([\w.\-/]+)\s*(?:###)?\s*\n```([\w]+)\n(.*?)```',
        re.DOTALL
    )

    matched_spans: list[tuple[int, int]] = []

    for m in pat1.finditer(text):
        fname   = m.group(1).strip()
        content = m.group(2).rstrip()
        files.append((_unique_name(fname), content))
        matched_spans.append((m.start(), m.end()))

    for m in pat1b.finditer(text):
        # Skip if already captured by pat1
        if any(s <= m.start() < e for s, e in matched_spans):
            continue
        fname_raw = m.group(1).strip()
        lang      = m.group(2).strip().lower()
        content   = m.group(3).rstrip()
        # Add extension if missing
        if '.' not in Path(fname_raw).name:
            ext_map = {v: k for k, v in _EXT_DEFAULTS.items() if '.' in v}
            ext = "." + (lang if lang not in ("javascript",) else "js")
            fname = fname_raw + ext
        else:
            fname = fname_raw
        files.append((_unique_name(fname), content))
        matched_spans.append((m.start(), m.end()))

    if files:
        return files

    # Pattern 2: fallback — bare ```lang blocks, infer filename from language
    pat2 = re.compile(r'```([\w]+)\n(.*?)```', re.DOTALL)
    lang_count: dict[str, int] = {}

    for m in pat2.finditer(text):
        lang    = m.group(1).strip().lower()
        content = m.group(2).rstrip()
        if not content.strip() or lang in ("", "text", "plaintext", "bash", "sh", "cmd"):
            continue
        default = _EXT_DEFAULTS.get(lang)
        if not default:
            continue
        lang_count[lang] = lang_count.get(lang, 0) + 1
        if lang_count[lang] == 1:
            fname = default
        else:
            stem = Path(default).stem
            ext  = Path(default).suffix
            fname = f"{stem}_{lang_count[lang]}{ext}"
        files.append((_unique_name(fname), content))

    return files


async def save_code_files(
    text:    str,
    project: str,
) -> list[str]:
    """
    Coder çıktısından dosyaları çıkarır ve workspace/{project}/ altına kaydeder.
    Returns: Kaydedilen dosya yollarının listesi.
    """
    pairs = extract_code_files(text)
    if not pairs:
        return []

    saved: list[str] = []
    for filename, content in pairs:
        path = await write_file(filename, content, workspace=True, project=project)
        saved.append(path)

    return saved
