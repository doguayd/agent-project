"""
Car Search Agent — Turbo
=========================
Persona : Hızlı, teknik, güvenilir bir araç danışmanı.
Görevi  : arabam.com'da araç arar, detayları çeker,
          kullanıcıya yapılandırılmış sonuçlar sunar.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from config import MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks
from tools.car_scraper import search_cars, CarListing, _parse_car_query


class CarAgent:
    """
    Kullanıcının araç sorgusunu işler:
    1. arabam.com'da arama yapar
    2. Yapılandırılmış JSON + özet metin döndürür
    """

    def __init__(self) -> None:
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm = create_llm(
            cfg["provider"],
            cfg["model"],
            temperature=0.3,
        )
        self._label = f"{cfg['provider']}:{cfg['model']}"

    async def _generate_summary(
        self,
        query:    str,
        listings: list[CarListing],
    ) -> str:
        """İlanlar hakkında kısa Türkçe özet üret."""
        if not listings:
            return (
                "Üzgünüm, bu kriterlere uygun araç bulunamadı. "
                "Lütfen farklı marka, fiyat aralığı veya yıl deneyin."
            )

        prices = []
        for l in listings:
            nums = re.findall(r"\d+", l.price.replace(".", "").replace(",", ""))
            if nums:
                try:
                    prices.append(int(nums[0]))
                except ValueError:
                    pass

        price_range = ""
        if prices:
            lo, hi = min(prices), max(prices)
            price_range = f"{lo:,} – {hi:,} TL"

        prompt = f"""Şu araç arama sonuçları için 2-3 cümle Türkçe özet yaz.
Arama: {query}
Bulunan ilan sayısı: {len(listings)}
Fiyat aralığı: {price_range}
Listelenen araçlar (ilk 5): {', '.join(l.title for l in listings[:5])}

Özet ton: teknik, bilgilendirici, gerçekçi."""

        msgs = [{"role": "user", "content": prompt}]
        try:
            raw = await self.llm.generate(msgs)
            return _strip_think_blocks(raw).strip()
        except Exception:
            return f"{len(listings)} araç bulundu. Fiyatlar: {price_range}."

    async def search(
        self,
        query: str,
        emit:  Emitter = noop,
    ) -> dict:
        """
        Ana arama metodu.

        Returns:
            {
              "success": bool,
              "listings": [CarListing.to_dict(), ...],
              "search_url": str,
              "summary": str,
              "query_params": dict,
              "elapsed_s": float,
            }
        """
        t0 = time.perf_counter()

        await emit(wrap("car.status", {
            "step": "parse", "message": "Araç sorgusu analiz ediliyor..."
        }))

        query_params = _parse_car_query(query)

        await emit(wrap("car.status", {
            "step":    "search",
            "message": f"arabam.com'da aranıyor...",
            "params":  {k: v for k, v in query_params.items() if v},
        }))

        listings, search_url = await search_cars(query, max_results=20)

        await emit(wrap("car.status", {
            "step":    "found",
            "message": f"{len(listings)} araç bulundu",
            "count":   len(listings),
            "url":     search_url,
        }))

        await emit(wrap("car.status", {
            "step": "summarize", "message": "Özet hazırlanıyor..."
        }))
        summary = await self._generate_summary(query, listings)

        elapsed = round(time.perf_counter() - t0, 1)
        await emit(wrap("car.done", {
            "count":     len(listings),
            "elapsed_s": elapsed,
            "summary":   summary,
        }))

        return {
            "success":     True,
            "listings":    [l.to_dict() for l in listings],
            "search_url":  search_url,
            "summary":     summary,
            "query_params": query_params,
            "elapsed_s":   elapsed,
        }
