"""
OSINT Agent — Sigma
====================
Persona : Sessiz, analitik, detaylı bir dijital araştırmacı.
Görevi  : maigret ile 3000+ sitede kullanıcı adı araması yapar,
          bulunan profilleri raporlar.
"""

from __future__ import annotations

import asyncio
import re
import time

from config import MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks
from tools.osint_tools import search_username


class OsintAgent:
    """
    Kullanıcı adı araştırması yapar:
    1. Sorgudaki kullanıcı adlarını tespit eder
    2. maigret ile 3000+ sitede tarar
    3. Bulunan profilleri raporlar
    """

    def __init__(self) -> None:
        cfg = MODELS.get("researcher", MODELS["fast"])
        self.llm = create_llm(
            cfg["provider"],
            cfg["model"],
            temperature=0.2,
        )

    # Türkçe eylem/sıfat kelimeleri — kullanıcı adı DEĞİL
    _STOP_WORDS = {
        "bul", "ara", "tara", "araştır", "bana", "için", "bu", "bir",
        "kullanıcı", "kullanıcısını", "kullanıcıadı", "kullanıcıadını",
        "profil", "profilini", "hesap", "hesabını", "hesabı",
        "username", "user", "search", "find", "lookup",
        "sitede", "platformda", "sosyal", "medya", "ağda",
        "kim", "kimdir", "hakkında", "ile", "ve", "veya",
        "lütfen", "acil", "hızlı", "tüm",
    }

    def _extract_usernames(self, query: str) -> list[str]:
        """Sorgudan kullanıcı adı(larını) çıkar."""
        # @ ile başlayanlar: @elonmusk
        at_names = re.findall(r"@(\w+)", query)
        if at_names:
            return at_names

        # Tırnak içindekiler: "elonmusk" veya 'elonmusk'
        quoted = re.findall(r'["\']([^"\']+)["\']', query)
        if quoted:
            return quoted

        # "kullanıcı adı: xxx", "username: xxx", "bul: xxx" — iki nokta sonrası
        kw_match = re.search(
            r"(?:kullanıcı\s*adı|username|user)[:\s]+(\S+)",
            query, re.IGNORECASE,
        )
        if kw_match:
            candidate = kw_match.group(1).strip(".,")
            if candidate.lower() not in self._STOP_WORDS:
                return [candidate]

        # "[username] kullanıcısını bul/ara" veya "bul [username]" deseni
        # Örnek: "elonmusk kullanıcısını bul" → elonmusk
        prefix_match = re.search(
            r"^(\w{3,})\s+(?:kullanıcı|kullanıcısını|profil|hesap)",
            query.strip(), re.IGNORECASE,
        )
        if prefix_match:
            candidate = prefix_match.group(1)
            if candidate.lower() not in self._STOP_WORDS:
                return [candidate]

        # "bul elonmusk" veya "ara elonmusk" — eylem sonrası kullanıcı adı
        suffix_match = re.search(
            r"(?:bul|ara|tara|araştır|find|lookup)\s+(\w{3,})",
            query, re.IGNORECASE,
        )
        if suffix_match:
            candidate = suffix_match.group(1)
            if candidate.lower() not in self._STOP_WORDS:
                return [candidate]

        # Stop-word olmayan kelimeleri bul, en uzun olanı al
        words = re.findall(r"\b\w{3,}\b", query)
        candidates = [
            w for w in words
            if w.lower() not in self._STOP_WORDS and re.match(r"^[a-zA-Z0-9_.\-]+$", w)
        ]
        if candidates:
            # En uzun alphanumeric kelimeyi kullanıcı adı say
            candidates.sort(key=len, reverse=True)
            return [candidates[0]]

        return []

    async def _generate_report(
        self,
        query:    str,
        username: str,
        result:   dict,
    ) -> str:
        """Araştırma sonuçlarını Türkçe özetle."""
        found    = result.get("found_count", 0)
        sites    = result.get("sites", [])
        err      = result.get("error")

        if err and not sites:
            return f"Araştırma sırasında hata oluştu: {err}"

        if not sites:
            return (
                f"**{username}** kullanıcı adı {found} sitede bulunamadı. "
                "Farklı bir kullanıcı adı deneyin veya büyük/küçük harf kontrolü yapın."
            )

        top_sites = [s["site"] for s in sites if s["status"] == "bulundu"][:10]

        prompt = f"""Şu OSINT araştırma sonuçları için Türkçe 3-4 cümle rapor yaz.
Aranan kullanıcı adı: {username}
Taranan site sayısı: ~3000
Profil bulunan site sayısı: {found}
Bulunan platformlar: {', '.join(top_sites[:15]) or 'yok'}

Rapor tonu: nötr, bilgilendirici, etik. Kişisel yargı yapma."""

        msgs = [{"role": "user", "content": prompt}]
        try:
            raw = await self.llm.generate(msgs)
            return _strip_think_blocks(raw).strip()
        except Exception:
            return (
                f"**{username}** kullanıcı adı {found} sitede bulundu. "
                f"Aktif platformlar: {', '.join(top_sites[:5])}."
            )

    async def search(
        self,
        query:     str,
        emit:      Emitter = noop,
        max_sites: int = 200,
    ) -> dict:
        """
        Ana OSINT arama metodu.

        Returns:
            {
              "success": bool,
              "username": str,
              "found_count": int,
              "sites": [...],
              "summary": str,
              "report_path": str | None,
              "elapsed_s": float,
            }
        """
        t0 = time.perf_counter()

        await emit(wrap("osint.status", {
            "step": "parse", "message": "Kullanıcı adı tespit ediliyor..."
        }))

        usernames = self._extract_usernames(query)

        if not usernames:
            return {
                "success":     False,
                "username":    "",
                "found_count": 0,
                "sites":       [],
                "summary":     "Kullanıcı adı tespit edilemedi. Örnek: '@kullanici_adi' veya 'kullanici_adi kullanıcısını bul'",
                "elapsed_s":   0,
            }

        username = usernames[0]  # İlk kullanıcı adını işle

        await emit(wrap("osint.status", {
            "step":     "search",
            "message":  f"'{username}' 3000+ sitede taranıyor...",
            "username": username,
        }))

        result = await search_username(
            username,
            max_sites=max_sites,
        )

        await emit(wrap("osint.status", {
            "step":    "found",
            "message": f"{result.get('found_count', 0)} profil bulundu",
            "count":   result.get("found_count", 0),
        }))

        await emit(wrap("osint.status", {
            "step": "summarize", "message": "Rapor hazırlanıyor..."
        }))

        summary = await self._generate_report(query, username, result)

        elapsed = round(time.perf_counter() - t0, 1)
        await emit(wrap("osint.done", {
            "username":    username,
            "found_count": result.get("found_count", 0),
            "elapsed_s":   elapsed,
            "summary":     summary,
        }))

        return {
            "success":     True,
            "username":    username,
            "found_count": result.get("found_count", 0),
            "sites":       result.get("sites", []),
            "summary":     summary,
            "report_path": result.get("report_path"),
            "elapsed_s":   elapsed,
        }
