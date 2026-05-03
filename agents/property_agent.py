"""
Property Search Agent — Lara
==============================
Persona : Meraklı, güvenilir, detay odaklı bir emlak danışmanı.
Görevi  : sahibinden.com'da ilan arar, detay çeker, mesafe hesaplar,
          kullanıcıya yapılandırılmış sonuçlar sunar.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from config import GOOGLE_MAPS_API_KEY, MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks
from tools.property_scraper import search_listings, fetch_listing_detail, Listing
from tools.maps_client import (
    enrich_listings_batch, parse_poi_request, ISTANBUL_POI_COORDS as ISTANBUL_POIS
)


class PropertyAgent:
    """
    Kullanıcının emlak sorgusunu işler:
    1. Sahibinden.com'da arama yapar
    2. İlan detaylarını çeker (opsiyonel)
    3. Mesafe hesaplar (Google Maps — API key varsa)
    4. Yapılandırılmış JSON + özet metin döndürür
    """

    def __init__(self) -> None:
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm = create_llm(
            cfg["provider"],
            cfg["model"],
            temperature=0.3,
        )
        self._label = f"{cfg['provider']}:{cfg['model']}"

    async def _interpret_query(self, raw_query: str) -> dict:
        """
        LLM yardımıyla kullanıcı sorgusunu yapılandır.
        Returns: {"search_query": ..., "pois": [...], "max_results": ..., "mode": ...}
        """
        prompt = f"""You are a Turkish real estate search assistant.
Parse this user query into a structured search request.

User query: "{raw_query}"

Respond with ONLY valid JSON:
{{
  "search_query": "<türkçe arama terimi: ilçe + oda + kategori + fiyat aralığı>",
  "pois": ["<POI1>", "<POI2>"],
  "max_results": <5-20>,
  "mode": "transit",
  "summary": "<1 cümle Türkçe özet: ne arıyoruz>"
}}

POI examples: "Kadıköy Metro", "metroya yürüme mesafesi", "Taksim Meydanı"
Only include POIs if the user explicitly asked for distance calculations.
If no distance request, set pois to [].
Respond only with JSON, no prose."""

        msgs = [{"role": "user", "content": prompt}]
        try:
            raw = await self.llm.generate(msgs)
            raw = _strip_think_blocks(raw)
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                return json.loads(m.group())
        except Exception:
            pass

        # Fallback: kullan raw query'yi doğrudan
        pois = parse_poi_request(raw_query)
        return {
            "search_query": raw_query,
            "pois":         pois,
            "max_results":  15,
            "mode":         "transit",
            "summary":      f"'{raw_query}' araması",
        }

    async def _generate_summary(
        self,
        query:    str,
        listings: list[Listing],
        pois:     list[str],
    ) -> str:
        """İlanlar hakkında kısa Türkçe özet üret."""
        if not listings:
            return (
                "Üzgünüm, bu arama kriterlerine uygun ilan bulunamadı. "
                "Lütfen farklı bir lokasyon, fiyat aralığı veya oda sayısı deneyin."
            )

        # En ucuz/pahalı fiyatları bul
        prices = []
        for l in listings:
            nums = re.findall(r"[\d.]+", l.price.replace(".", ""))
            if nums:
                try:
                    prices.append(int(nums[0]))
                except ValueError:
                    pass

        price_range = ""
        if prices:
            lo, hi = min(prices), max(prices)
            price_range = f"{lo:,} – {hi:,} TL"

        has_distances = any(l.distances for l in listings)
        dist_note = ""
        if has_distances and pois:
            best = min(
                (l for l in listings if l.distances),
                key=lambda l: next(iter(l.distances.values()), {}).get("duration", "999"),
                default=None
            )
            if best and best.distances:
                first_poi = next(iter(best.distances))
                dur = best.distances[first_poi].get("duration", "?")
                dist_note = f" En yakın {first_poi}: {dur} ({best.title[:40]})."

        prompt = f"""Şu emlak arama sonuçları için 2-3 cümle Türkçe özet yaz.
Arama: {query}
Bulunan ilan sayısı: {len(listings)}
Fiyat aralığı: {price_range}
{dist_note}

Özet ton: samimi, yararlı, gerçekçi. Fazla iyimser olma."""

        msgs = [{"role": "user", "content": prompt}]
        try:
            raw = await self.llm.generate(msgs)
            return _strip_think_blocks(raw).strip()
        except Exception:
            return f"{len(listings)} ilan bulundu. Fiyatlar: {price_range}."

    async def search(
        self,
        query:        str,
        emit:         Emitter = noop,
        fetch_detail: bool    = False,
    ) -> dict:
        """
        Ana arama metodu.

        Returns:
            {
              "success": bool,
              "listings": [Listing.to_dict(), ...],
              "search_url": str,
              "summary": str,
              "pois": [...],
              "query_info": {...},
            }
        """
        t0 = time.perf_counter()

        # 1. Sorguyu yorumla
        await emit(wrap("property.status", {
            "step": "parse", "message": "Sorgu analiz ediliyor..."
        }))
        query_info = await self._interpret_query(query)
        search_query = query_info.get("search_query", query)
        pois         = query_info.get("pois", [])
        max_results  = query_info.get("max_results", 15)
        mode         = query_info.get("mode", "transit")
        summary_hint = query_info.get("summary", "")

        await emit(wrap("property.status", {
            "step": "search",
            "message": f"emlakjet.com'da aranıyor: {summary_hint}",
            "search_query": search_query,
        }))

        # 2. emlakjet.com araması (otomatik fallback geniş sorguya geçer)
        listings, search_url = await search_listings(search_query, max_results=max_results)

        if not listings:
            await emit(wrap("property.status", {
                "step": "retry",
                "message": "Sonuç bulunamadı, daha geniş aramaya geçiliyor...",
            }))

        await emit(wrap("property.status", {
            "step": "found",
            "message": f"{len(listings)} ilan bulundu",
            "count":   len(listings),
            "url":     search_url,
        }))

        # 3. Detay sayfaları (opsiyonel, ilk 5 ilan)
        if fetch_detail and listings:
            await emit(wrap("property.status", {
                "step": "detail",
                "message": f"İlan detayları çekiliyor ({min(5, len(listings))} ilan)...",
            }))
            detail_tasks = [
                fetch_listing_detail(l.url) for l in listings[:5]
            ]
            details = await asyncio.gather(*detail_tasks, return_exceptions=True)
            for listing, detail in zip(listings[:5], details):
                if isinstance(detail, dict):
                    listing.description = detail.get("description", "")
                    listing.lat         = detail.get("lat")
                    listing.lng         = detail.get("lng")

        # 4. Mesafe hesabı (sadece API key varsa)
        if pois and GOOGLE_MAPS_API_KEY and listings:
            await emit(wrap("property.status", {
                "step": "distance",
                "message": f"Mesafeler hesaplanıyor: {', '.join(pois[:3])}...",
                "pois":    pois,
            }))
            await enrich_listings_batch(
                listings[:10],  # ilk 10 ilan için mesafe hesapla
                pois, GOOGLE_MAPS_API_KEY, mode,
                max_concurrent=3,
            )

        # 5. Özet
        await emit(wrap("property.status", {
            "step": "summarize", "message": "Özet hazırlanıyor..."
        }))
        summary = await self._generate_summary(query, listings, pois)

        elapsed = round(time.perf_counter() - t0, 1)
        await emit(wrap("property.done", {
            "count":   len(listings),
            "elapsed_s": elapsed,
            "summary": summary,
        }))

        return {
            "success":    True,
            "listings":   [l.to_dict() for l in listings],
            "search_url": search_url,
            "summary":    summary,
            "pois":       pois,
            "query_info": query_info,
            "elapsed_s":  elapsed,
        }
