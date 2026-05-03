"""
Web Search tools for the agent system.
Extracted and simplified from Master-MCP (tools/services/knowledge/).

Provides:
  - web_search()           — DuckDuckGo text search (with hard timeout)
  - stackoverflow_search() — StackExchange API (accepted answers, with hard timeout)
  - research_search()      — Combined, formatted context block for agents
  - quick_search()         — Fast web-only search with tighter limits (for coder/debugger)

All functions return an empty string on failure (network down, missing deps, timeout, etc.)
so agents degrade gracefully in offline mode.

TIMEOUT POLICY
  • Each individual search: 8 seconds max
  • research_search() total: 12 seconds max
  • quick_search() total:     6 seconds max
"""

from __future__ import annotations

import asyncio
import html
import re

# DuckDuckGo — try new package name first, fall back to old
_DDGS_AVAILABLE = False
try:
    from ddgs import DDGS          # pip install ddgs  (yeni isim)
    _DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS   # eski isim (fallback)
        _DDGS_AVAILABLE = True
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _run_with_timeout(coro, seconds: float) -> str:
    """
    Run `coro` with a hard wall-clock timeout.
    Returns '' if it times out or raises any exception.
    """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except (asyncio.TimeoutError, Exception):
        return ""


# ---------------------------------------------------------------------------
# DuckDuckGo search
# ---------------------------------------------------------------------------

async def _web_search_inner(query: str, max_results: int) -> str:
    if not _DDGS_AVAILABLE:
        return ""
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        lambda: list(DDGS().text(query, max_results=max_results))
    )
    if not results:
        return ""
    lines = []
    for r in results:
        title = r.get("title", "")
        body  = r.get("body",  "")[:400]     # cap per-result body
        href  = r.get("href",  "")
        lines.append(f"**{title}**\n{body}\nURL: {href}")
    return "\n\n".join(lines)


async def web_search(query: str, max_results: int = 4) -> str:
    """
    DuckDuckGo text search with 8-second hard timeout.
    Returns '' if unavailable, failed, or timed out.
    """
    return await _run_with_timeout(
        _web_search_inner(query[:200], max_results),
        seconds=8.0,
    )


# ---------------------------------------------------------------------------
# StackOverflow search
# ---------------------------------------------------------------------------

def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(text).strip()


async def _stackoverflow_search_inner(query: str, max_results: int) -> str:
    import requests
    params = {
        "q":        query,
        "site":     "stackoverflow",
        "accepted": "True",
        "order":    "desc",
        "sort":     "votes",
        "filter":   "withbody",
        "pagesize": max_results,
    }
    loop  = asyncio.get_event_loop()
    items = await loop.run_in_executor(
        None,
        lambda: requests.get(
            "https://api.stackexchange.com/2.3/search/advanced",
            params=params, timeout=7
        ).json().get("items", [])[:max_results],
    )
    if not items:
        return ""
    lines = []
    for item in items:
        title = _clean_html(item.get("title", ""))
        link  = item.get("link", "")
        body  = _clean_html(item.get("body", ""))[:500]
        lines.append(f"**{title}**\n{body}\nURL: {link}")
    return "\n\n".join(lines)


async def stackoverflow_search(query: str, max_results: int = 2) -> str:
    """
    StackExchange API with 8-second hard timeout.
    Returns '' on failure.
    """
    return await _run_with_timeout(
        _stackoverflow_search_inner(query[:200], max_results),
        seconds=8.0,
    )


# ---------------------------------------------------------------------------
# Combined helper — for Aria (Researcher)
# ---------------------------------------------------------------------------

async def research_search(query: str, max_web: int = 4, max_so: int = 2) -> str:
    """
    Runs DuckDuckGo + StackOverflow in parallel, total cap 12 seconds.
    Returns a formatted context block, or '' if both fail.
    """
    query_short = query[:200]

    async def _both() -> str:
        web_result, so_result = await asyncio.gather(
            web_search(query_short, max_results=max_web),
            stackoverflow_search(query_short, max_results=max_so),
        )
        parts: list[str] = []
        if web_result:
            parts.append(f"[WEB SEARCH RESULTS]\n{web_result}")
        if so_result:
            parts.append(f"[STACKOVERFLOW RESULTS]\n{so_result}")
        return "\n\n".join(parts)

    return await _run_with_timeout(_both(), seconds=12.0)


# ---------------------------------------------------------------------------
# Quick search — for Kenji (Coder) and Neo (Debugger)
# ---------------------------------------------------------------------------

async def quick_search(query: str, max_results: int = 3) -> str:
    """
    Fast web-only search with a 6-second total timeout.
    Intended for coder/debugger agents that need a fast lookup, not deep research.
    Returns '' on failure or timeout.
    """
    return await _run_with_timeout(
        _web_search_inner(query[:150], max_results),
        seconds=6.0,
    )
