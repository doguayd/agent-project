"""
Finans Araçları — Nova için
============================
yfinance ile hisse senedi, kripto, döviz verileri.
DuckDuckGo ile piyasa haberleri.
Tamamen lokal, API key gerektirmez.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional


# ─── Sembol Normalizasyonu ────────────────────────────────────────────────────

TICKER_ALIASES: dict[str, str] = {
    # Türk hisseleri
    "thyao": "THYAO.IS", "garanti": "GARAN.IS", "akbank": "AKBNK.IS",
    "isctr": "ISCTR.IS", "eregli": "EREGL.IS", "bimas": "BIMAS.IS",
    "tupras": "TUPRS.IS", "koç": "KCHOL.IS", "sabancı": "SAHOL.IS",
    "togg": "TOGG.IS",
    # Kripto
    "bitcoin": "BTC-USD", "btc": "BTC-USD",
    "ethereum": "ETH-USD", "eth": "ETH-USD",
    "solana": "SOL-USD", "sol": "SOL-USD",
    "bnb": "BNB-USD", "xrp": "XRP-USD",
    "doge": "DOGE-USD", "dogecoin": "DOGE-USD",
    "avax": "AVAX-USD", "polkadot": "DOT-USD",
    # Büyük şirketler (Türkçe yazılış)
    "apple": "AAPL", "elma": "AAPL",
    "google": "GOOGL", "microsoft": "MSFT",
    "amazon": "AMZN", "tesla": "TSLA",
    "nvidia": "NVDA", "meta": "META",
    "netflix": "NFLX", "openai": "MSFT",
    # Döviz
    "dolar": "USDTRY=X", "euro": "EURTRY=X",
    "usd": "USDTRY=X", "eur": "EURTRY=X",
    "altın": "GC=F", "gold": "GC=F",
    "petrol": "CL=F", "oil": "CL=F",
    # Endeksler
    "dow jones": "^DJI", "sp500": "^GSPC", "nasdaq": "^IXIC",
    "bist100": "XU100.IS", "bist": "XU100.IS",
}

def normalize_ticker(query: str) -> str:
    """Doğal dil sorgudan ticker sembolü bul."""
    q = query.lower().strip()
    for alias, ticker in TICKER_ALIASES.items():
        if alias in q:
            return ticker
    # Büyük harfli sembol aramaya çalış
    import re
    m = re.search(r"\b([A-Z]{2,5}(?:\.IS)?)\b", query)
    if m:
        return m.group(1)
    # İlk kelimeyi dene
    first = q.split()[0].upper() if q else ""
    return first or query.upper()


# ─── Veri Çekme ──────────────────────────────────────────────────────────────

async def get_stock_info(ticker: str, period: str = "1mo") -> dict:
    """
    yfinance ile hisse/kripto/döviz bilgisi çek.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max
    """
    try:
        import yfinance as yf
        loop = asyncio.get_event_loop()

        def _fetch():
            t = yf.Ticker(ticker)
            info    = t.info or {}
            hist    = t.history(period=period)
            fast    = t.fast_info

            current_price = None
            try:
                current_price = fast.last_price
            except Exception:
                pass

            if current_price is None:
                current_price = info.get("currentPrice") or info.get("regularMarketPrice")

            prev_close = None
            try:
                prev_close = fast.previous_close
            except Exception:
                prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

            change_pct = None
            if current_price and prev_close and prev_close != 0:
                change_pct = round((current_price - prev_close) / prev_close * 100, 2)

            # Tarihsel veri özeti
            hist_data = []
            if not hist.empty:
                for date, row in hist.tail(30).iterrows():
                    hist_data.append({
                        "date":  str(date.date()),
                        "close": round(float(row["Close"]), 4),
                        "volume": int(row.get("Volume", 0)),
                    })

            return {
                "ticker":        ticker,
                "name":          info.get("longName") or info.get("shortName") or ticker,
                "currency":      info.get("currency", "USD"),
                "current_price": round(current_price, 4) if current_price else None,
                "prev_close":    round(prev_close, 4)    if prev_close    else None,
                "change_pct":    change_pct,
                "market_cap":    info.get("marketCap"),
                "52w_high":      info.get("fiftyTwoWeekHigh"),
                "52w_low":       info.get("fiftyTwoWeekLow"),
                "pe_ratio":      info.get("trailingPE"),
                "description":   (info.get("longBusinessSummary") or "")[:500],
                "sector":        info.get("sector", ""),
                "industry":      info.get("industry", ""),
                "history":       hist_data,
                "period":        period,
            }

        return await loop.run_in_executor(None, _fetch)

    except ImportError:
        return {"error": "yfinance kurulu değil: pip install yfinance"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


async def get_multiple_tickers(tickers: list[str], period: str = "1mo") -> list[dict]:
    """Birden fazla ticker'ı paralel sorgula."""
    tasks = [get_stock_info(t, period) for t in tickers]
    return await asyncio.gather(*tasks)


async def search_finance_news(query: str, max_results: int = 5) -> str:
    """DuckDuckGo ile finans haberleri ara."""
    try:
        from tools.web_search import web_search
        return await web_search(f"{query} hisse fiyat finans 2025", max_results=max_results)
    except Exception:
        return ""


async def get_market_summary() -> dict:
    """Ana endeksler ve önemli varlıkların özet tablosu."""
    tickers = ["^GSPC", "^IXIC", "^DJI", "XU100.IS", "BTC-USD", "USDTRY=X", "EURTRY=X", "GC=F"]
    results = await get_multiple_tickers(tickers, period="5d")

    summary = {}
    for r in results:
        if "error" not in r and r.get("current_price"):
            summary[r["ticker"]] = {
                "name":       r["name"],
                "price":      r["current_price"],
                "currency":   r["currency"],
                "change_pct": r["change_pct"],
            }
    return summary
