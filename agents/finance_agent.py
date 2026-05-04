"""
Finance Agent — Nova
=====================
Persona : Soğukkanlı, veri odaklı, tarafsız bir finans analisti.
Görevi  : Hisse, kripto, döviz ve endeks verileri çeker;
          piyasa haberleri ile birlikte analiz raporları üretir.
"""

from __future__ import annotations

import asyncio
import re
import time

from config import MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks
from tools.finance_tools import (
    normalize_ticker, get_stock_info, get_market_summary,
    search_finance_news, get_multiple_tickers,
)


class FinanceAgent:
    """
    Finansal veri araştırması yapar:
    1. Kullanıcı sorgusundan varlık tespit eder
    2. yfinance ile gerçek zamanlı veri çeker
    3. Haberlerle birlikte analiz raporu üretir
    """

    def __init__(self) -> None:
        cfg = MODELS.get("researcher", MODELS["fast"])
        self.llm = create_llm(
            cfg["provider"],
            cfg["model"],
            temperature=0.3,
        )

    def _detect_query_type(self, query: str) -> str:
        """Sorgu türünü tespit et."""
        q = query.lower()
        if any(w in q for w in ["piyasa", "endeks", "genel", "özet", "bugün ne oldu"]):
            return "market_summary"
        if any(w in q for w in ["karşılaştır", "vs", "hangisi", "ile"]):
            return "compare"
        return "single"

    def _extract_tickers(self, query: str) -> list[str]:
        """Sorgudaki varlıkları ticker'a çevir."""
        q = query.lower()

        # Büyük harfli semboller (AAPL, BTC-USD gibi)
        explicit = re.findall(r"\b([A-Z]{2,5}(?:-USD|\.IS)?)\b", query)

        # Bilinen alias'lar
        from tools.finance_tools import TICKER_ALIASES
        found = []
        for alias, ticker in TICKER_ALIASES.items():
            if alias in q:
                found.append(ticker)

        # Birleştir, tekrarları kaldır
        all_tickers = list(dict.fromkeys(found + explicit))
        return all_tickers[:5] if all_tickers else [normalize_ticker(query)]

    async def _build_analysis(
        self,
        query:    str,
        data:     list[dict],
        news:     str,
        qtype:    str,
    ) -> str:
        """LLM ile analiz raporu üret."""
        data_str = ""
        for d in data:
            if "error" in d:
                continue
            chg = f"{d.get('change_pct', 0):+.2f}%" if d.get("change_pct") is not None else "?"
            data_str += (
                f"\n• {d.get('name', d['ticker'])} ({d['ticker']}): "
                f"{d.get('current_price', '?')} {d.get('currency', '')} "
                f"({chg})"
            )

        if not data_str:
            return "Veri çekilemedi. Ticker sembolünü kontrol edin veya farklı bir varlık deneyin."

        prompt = f"""Şu finansal veriler için Türkçe 4-5 cümle analiz yaz.
Kullanıcı sorusu: {query}
Veriler:{data_str}

{f'İlgili haberler: {news[:800]}' if news else ''}

Analiz kuralları:
- Kesin yatırım tavsiyesi VERME
- Verileri objektif yorumla
- Önemli değişimleri vurgula
- Türkçe, anlaşılır, teknik ama erişilebilir yaz"""

        msgs = [{"role": "user", "content": prompt}]
        try:
            raw = await self.llm.generate(msgs)
            return _strip_think_blocks(raw).strip()
        except Exception:
            prices = [f"{d.get('name', d['ticker'])}: {d.get('current_price', '?')} ({d.get('change_pct', '?')}%)"
                      for d in data if "error" not in d]
            return "Güncel veriler: " + " | ".join(prices)

    async def analyze(
        self,
        query:  str,
        emit:   Emitter = noop,
        period: str = "1mo",
    ) -> dict:
        """
        Ana analiz metodu.

        Returns:
            {
              "success": bool,
              "tickers": [...],
              "data": [...],
              "summary": str,
              "news": str,
              "elapsed_s": float,
            }
        """
        t0 = time.perf_counter()

        await emit(wrap("finance.status", {
            "step": "parse", "message": "Finans sorgusu analiz ediliyor..."
        }))

        qtype   = self._detect_query_type(query)
        tickers = self._extract_tickers(query)

        await emit(wrap("finance.status", {
            "step":    "fetch",
            "message": f"Veri çekiliyor: {', '.join(tickers)}...",
            "tickers": tickers,
        }))

        # Piyasa özeti mi yoksa spesifik varlık mı?
        if qtype == "market_summary":
            raw_data_dict = await get_market_summary()
            data = list(raw_data_dict.values()) if raw_data_dict else []
        else:
            data = await get_multiple_tickers(tickers, period=period)

        await emit(wrap("finance.status", {
            "step": "news", "message": "Haberler aranıyor..."
        }))

        news = await search_finance_news(query)

        await emit(wrap("finance.status", {
            "step": "analyze", "message": "Analiz hazırlanıyor..."
        }))

        summary = await self._build_analysis(query, data, news, qtype)

        elapsed = round(time.perf_counter() - t0, 1)
        await emit(wrap("finance.done", {
            "tickers":   tickers,
            "elapsed_s": elapsed,
            "summary":   summary,
        }))

        return {
            "success":   True,
            "tickers":   tickers,
            "data":      data,
            "summary":   summary,
            "news":      news,
            "elapsed_s": elapsed,
        }
