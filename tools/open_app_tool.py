"""
Uygulama Açma Aracı — Windows
================================
Windows'ta uygulama başlatır.
macOS 'open -a' yerine 'start' veya tam yol kullanır.

JARVIS (Alp Ünlü, @alppunlu) projesinden uyarlanmıştır.
"""

from __future__ import annotations

import os
import shutil
import subprocess


# Türkçe/kısa isim → Windows uygulama adı / yürütülebilir dosya
APP_ALIASES: dict[str, str] = {
    # Tarayıcılar
    "chrome":         "chrome",
    "google chrome":  "chrome",
    "firefox":        "firefox",
    "edge":           "msedge",
    "microsoft edge": "msedge",

    # Geliştirici araçları
    "vscode":          "code",
    "vs code":         "code",
    "code":            "code",
    "visual studio code": "code",
    "terminal":        "wt",        # Windows Terminal
    "powershell":      "powershell",
    "cmd":             "cmd",
    "notepad":         "notepad",
    "notepad++":       "notepad++",

    # Medya
    "spotify":         "Spotify",
    "vlc":             "vlc",
    "itunes":          "iTunes",

    # İletişim
    "whatsapp":        "WhatsApp",
    "telegram":        "Telegram",
    "discord":         "Discord",
    "slack":           "Slack",
    "zoom":            "Zoom",
    "teams":           "Teams",
    "microsoft teams": "Teams",

    # Ofis
    "word":            "WINWORD",
    "excel":           "EXCEL",
    "powerpoint":      "POWERPNT",
    "outlook":         "OUTLOOK",
    "onenote":         "ONENOTE",

    # Windows araçları
    "dosya gezgini":   "explorer",
    "file explorer":   "explorer",
    "explorer":        "explorer",
    "hesap makinesi":  "calc",
    "calculator":      "calc",
    "task manager":    "taskmgr",
    "görev yöneticisi": "taskmgr",
    "ayarlar":         "ms-settings:",
    "settings":        "ms-settings:",
    "paint":           "mspaint",
    "snip":            "SnippingTool",
    "ekran alıntısı":  "SnippingTool",

    # Diğer
    "notion":          "Notion",
    "docker":          "Docker Desktop",
    "postman":         "Postman",
    "figma":           "Figma",
}


def open_app(app_name: str) -> str:
    """Windows'ta uygulama aç. Başarı veya hata mesajı döndürür."""
    if not app_name or not app_name.strip():
        return "Uygulama adı belirtilmedi."

    normalized = app_name.lower().strip()
    resolved   = APP_ALIASES.get(normalized, app_name)

    # ms-settings: gibi özel URI'lar
    if ":" in resolved and not resolved.endswith(".exe"):
        try:
            os.startfile(resolved)
            return f"{app_name} açıldı."
        except Exception as exc:
            return f"'{app_name}' açılamadı: {exc}"

    # PATH'te varsa direkt çalıştır
    if shutil.which(resolved):
        try:
            subprocess.Popen(
                [resolved],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            return f"{app_name} başlatıldı."
        except Exception as exc:
            return f"'{app_name}' başlatılamadı: {exc}"

    # Windows 'start' komutu ile dene (uygulamanın adını bilir)
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", resolved],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        return f"{app_name} başlatıldı."
    except Exception as exc:
        return f"'{app_name}' bulunamadı veya açılamadı: {exc}"
