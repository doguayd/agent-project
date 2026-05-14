"""
WhatsApp Aracı — Windows
==========================
WhatsApp Web URL scheme ile mesaj taslağı açar.
macOS AppleScript/osascript yerine Windows webbrowser + pyperclip kullanır.

Otomatik gönderim için pywinauto veya keyboard paketi gerekir (opsiyonel).

JARVIS (Alp Ünlü, @alppunlu) projesinden uyarlanmıştır.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
import urllib.parse
import webbrowser
from pathlib import Path

from core.user_memory import load_memory, update_memory


PHONEBOOK_FILE = Path("workspace/whatsapp_phonebook.json")


# ── Telefon numarası normalizasyonu ──────────────────────────────────────────

def _normalize_phone(number: str) -> str:
    digits = re.sub(r"\D+", "", number or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = "90" + digits[1:]
    elif len(digits) == 10:
        digits = "90" + digits
    if not (8 <= len(digits) <= 15):
        raise ValueError(
            f"Geçersiz telefon numarası: '{number}'. "
            "Uluslararası format gerekli, örn: +905551112233"
        )
    return digits


def _normalize_lookup(text: str) -> str:
    text = (text or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ı", "i")
    return " ".join(text.split())


def _contact_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize_lookup(name)).strip("_") or "contact"


# ── Rehber yönetimi ───────────────────────────────────────────────────────────

def _load_phonebook() -> dict:
    try:
        if PHONEBOOK_FILE.exists():
            import json
            return json.loads(PHONEBOOK_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_phonebook(pb: dict):
    import json
    PHONEBOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    PHONEBOOK_FILE.write_text(json.dumps(pb, indent=2, ensure_ascii=False), encoding="utf-8")


def _contact_candidates() -> list[dict]:
    candidates = []
    memory = load_memory()
    for source_name, source in (
        ("whatsapp", memory.get("whatsapp_contacts", {})),
        ("phonebook", _load_phonebook()),
    ):
        if not isinstance(source, dict):
            continue
        for key, entry in source.items():
            if not isinstance(entry, dict):
                continue
            item = dict(entry)
            item.setdefault("display_name", key)
            item["_source"] = source_name
            item["_key"] = key
            candidates.append(item)
    return candidates


def _find_contact(recipient_name: str) -> dict | None:
    needle = _normalize_lookup(recipient_name)
    if not needle:
        return None
    best, best_score = None, 0
    for entry in _contact_candidates():
        names = [entry.get("display_name", ""), entry.get("_key", "")]
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            names.extend(str(a) for a in aliases)
        for name in names:
            cand = _normalize_lookup(name)
            if not cand:
                continue
            if cand == needle:
                score = 300
            elif cand.startswith(needle) or needle.startswith(cand):
                score = 220
            elif needle in cand:
                score = 160
            elif all(p in cand for p in needle.split()):
                score = 120
            else:
                score = 0
            if score > best_score:
                best_score, best = score, entry
    return best


def save_whatsapp_contact(display_name: str, phone_number: str, aliases: str = "") -> str:
    """Kişiyi kalıcı WhatsApp rehberine ekle."""
    if not display_name.strip():
        return "Kişi adı boş olamaz."
    try:
        normalized = _normalize_phone(phone_number)
    except ValueError as exc:
        return str(exc)

    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
    key = _contact_key(display_name)
    update_memory({
        "whatsapp_contacts": {
            key: {
                "value": f"+{normalized}",
                "display_name": display_name.strip(),
                "aliases": alias_list,
            }
        }
    })
    suffix = f" (takma adlar: {', '.join(alias_list)})" if alias_list else ""
    return f"{display_name.strip()} WhatsApp rehberine kaydedildi.{suffix}"


# ── Mesaj gönderme ────────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str):
    """Metni panoya kopyala (Windows)."""
    try:
        import pyperclip          # type: ignore
        pyperclip.copy(text)
        return
    except ImportError:
        pass
    # Fallback: clip komutu (Windows built-in)
    try:
        subprocess.run("clip", input=text.encode("utf-16le"), check=True, timeout=5)
    except Exception:
        pass


def _auto_send_whatsapp_web(delay_s: float = 2.5) -> bool:
    """
    WhatsApp Web açıldıktan sonra Enter gönderir.
    keyboard paketi gerekli (pip install keyboard).
    """
    try:
        import time
        import keyboard          # type: ignore
        time.sleep(delay_s)
        keyboard.send("enter")
        return True
    except ImportError:
        return False
    except Exception:
        return False


def send_whatsapp_message(
    message: str,
    phone_number: str = "",
    recipient_name: str = "",
    send_now: bool = False,
) -> str:
    """
    WhatsApp Web URL scheme ile sohbet taslağı açar.
    send_now=True ise keyboard ile Enter göndermeyi dener.
    """
    if not message or not message.strip():
        return "Mesaj boş olamaz."

    normalized_phone = ""
    if phone_number and phone_number.strip():
        try:
            normalized_phone = _normalize_phone(phone_number)
        except ValueError as exc:
            return str(exc)

    resolved_name = (recipient_name or "").strip()
    contact = _find_contact(resolved_name) if resolved_name else None

    if contact and not normalized_phone:
        stored = str(contact.get("value", "")).strip()
        try:
            normalized_phone = _normalize_phone(stored)
        except ValueError:
            normalized_phone = ""
        resolved_name = contact.get("display_name", resolved_name) or resolved_name

    if not normalized_phone:
        if resolved_name:
            return (
                f"'{resolved_name}' için kayıtlı telefon numarası bulamadım. "
                "Önce 'whatsapp kişi kaydet' ile numarasını kaydet."
            )
        return "WhatsApp mesajı için telefon numarası veya kayıtlı kişi adı gerekli."

    encoded = urllib.parse.quote(message.strip())
    url = f"https://web.whatsapp.com/send?phone={normalized_phone}&text={encoded}"

    try:
        _copy_to_clipboard(message.strip())
        webbrowser.open(url)
    except Exception as exc:
        return f"WhatsApp Web açılamadı: {exc}"

    label = resolved_name or f"+{normalized_phone}"

    if send_now:
        sent = _auto_send_whatsapp_web(delay_s=3.0)
        if sent:
            return f"WhatsApp Web üzerinden {label} kişisine mesaj gönderildi ✅"
        return (
            f"WhatsApp Web {label} için açıldı. "
            "Otomatik gönderim için 'pip install keyboard' gerekli — "
            "sayfada Enter'a basarak gönderebilirsin."
        )

    return (
        f"WhatsApp Web {label} için açıldı, mesaj hazır. "
        "Göndermek için Enter'a bas."
    )
