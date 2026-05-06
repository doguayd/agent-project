"""
Browser Extension Agent — Atlas (Extension Mode)
=================================================
Chrome eklentisi üzerinden kullanıcının gerçek Chrome tarayıcısını kontrol eder.
Playwright açmaz — kullanıcının kendi Chrome'unda yeni sekme açar.

Avantajları:
  - Gerçek Chrome (bot tespiti neredeyse yok)
  - Kullanıcının mevcut çerezleri ve oturumları aktif
  - İnsan gibi CDP tabanlı fare/klavye kontrolü (Bezier yolu)
  - Playwright'ten çok daha hızlı ve güvenilir
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.parse
from typing import Any, Callable

from config import MODELS
from core.events import Emitter, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks

# ── Türkçe e-ticaret site bilgisi ────────────────────────────────────────────
# Her kategori için hangi siteleri dene, URL şablonları neler
_SITE_KNOWLEDGE = {
    # Genel e-ticaret
    "trendyol": {
        "search_url": "https://www.trendyol.com/sr?q={query}",
        "product_sel": ".p-card-wrppr",
        "name_sel":    ".prdct-desc-cntnr-name",
        "price_sel":   ".prc-box-dscntd, .prc-box-sllng-prc",
    },
    "hepsiburada": {
        "search_url": "https://www.hepsiburada.com/ara?q={query}",
        "product_sel": "[data-test-id='product-card-wrapper']",
        "name_sel":    "[data-test-id='product-card-name']",
        "price_sel":   "[data-test-id='product-card-price']",
    },
    "amazon_tr": {
        "search_url": "https://www.amazon.com.tr/s?k={query}&language=tr_TR",
        "product_sel": "[data-component-type='s-search-result']",
        "name_sel":    "h2 a span",
        "price_sel":   ".a-price-whole",
    },
    "n11": {
        "search_url": "https://www.n11.com/arama?q={query}",
        "product_sel": ".pro-list-item",
        "name_sel":    ".pro-title",
        "price_sel":   ".newPrice ins",
    },
    "gittigidiyor": {
        "search_url": "https://www.gittigidiyor.com/arama?k={query}",
        "product_sel": ".item-box",
        "name_sel":    ".item-name",
        "price_sel":   ".price",
    },
    "ciceksepeti": {
        "search_url": "https://www.ciceksepeti.com/arama?q={query}",
        "product_sel": ".product-item",
        "name_sel":    ".product-name",
        "price_sel":   ".price",
    },
    # Araba
    "sahibinden": {
        "search_url": "https://www.sahibinden.com/arama?query={query}",
        "product_sel": ".searchResultsItem",
        "name_sel":    ".classifiedTitle",
        "price_sel":   ".searchResultsPriceValue",
    },
    # Yazılım/tech
    "teknosa": {
        "search_url": "https://www.teknosa.com/arama?q={query}",
        "product_sel": ".product-item",
        "name_sel":    ".product-name",
        "price_sel":   ".price",
    },
    "mediamarkt": {
        "search_url": "https://www.mediamarkt.com.tr/tr/search.html?query={query}",
        "product_sel": "[data-test='product-card']",
        "name_sel":    "[data-test='product-title']",
        "price_sel":   "[data-test='product-price']",
    },
}

# Görevden site seçici: anahtar kelimeler → hangi siteleri kullan
_SITE_SELECTORS = [
    (["trendyol"], ["trendyol"]),
    (["hepsiburada"], ["hepsiburada"]),
    (["n11"], ["n11"]),
    (["amazon"], ["amazon_tr"]),
    (["gittigidiyor"], ["gittigidiyor"]),
    (["teknosa"], ["teknosa"]),
    (["mediamarkt", "media markt"], ["mediamarkt"]),
    (["sahibinden", "araç", "araba", "otomobil"], ["sahibinden"]),
    # Belirli bir site belirtilmemişse en popülerleri dene
]

def _pick_sites(task: str) -> list[str]:
    """Görev metninden hangi sitelerin aranacağını seç."""
    t = task.lower()
    for keywords, sites in _SITE_SELECTORS:
        if any(k in t for k in keywords):
            return sites
    # Varsayılan: Trendyol → Hepsiburada → N11
    return ["trendyol", "hepsiburada", "n11"]

def _build_search_url(site_key: str, query: str) -> str:
    """Site için arama URL'si oluştur."""
    info = _SITE_KNOWLEDGE.get(site_key, {})
    tmpl = info.get("search_url", f"https://www.google.com/search?q={{}}")
    return tmpl.format(query=urllib.parse.quote(query))


# ── Site'e özgü kategori URL'leri ────────────────────────────────────────────
# Bazı sitelerde arama çalışmaz — doğrudan kategori sayfasına gitmek gerekir.
# LLM bu bilgiyi plan yaparken kullanır.
_CATEGORY_KNOWLEDGE = {
    "asus.com/tr": {
        "not": "ASUS TR arama motoru ürünleri DEĞİL haberleri döndürür. Ürün bulmak için kategori URL'leri kullan.",
        "categories": {
            "çanta|sırt çantası|backpack|bag":
                "https://www.asus.com/tr/accessories/apparel-bags-and-gear/",
            "rog çanta|gaming backpack":
                "https://www.asus.com/tr/accessories/apparel-bags-and-gear/rog--republic-of-gamers/",
            "tuf çanta":
                "https://www.asus.com/tr/accessories/apparel-bags-and-gear/tuf-gaming/",
            "proart çanta":
                "https://www.asus.com/tr/accessories/apparel-bags-and-gear/proart/",
            "klavye":
                "https://www.asus.com/tr/accessories/keyboards/",
            "mouse":
                "https://www.asus.com/tr/accessories/mice-mouse-pads/",
            "laptop|dizüstü":
                "https://www.asus.com/tr/laptops/for-home/all-series/filter?Series=ROG-Republic-of-Gamers,TUF-Gaming,Zenbook,Vivobook",
        }
    },
    "asus.com": {
        "not": "ASUS global arama ürünleri döndürmez. Kategori sayfalarını kullan.",
        "categories": {
            "bag|backpack|çanta":
                "https://www.asus.com/accessories/apparel-bags-and-gear/",
        }
    }
}

def _get_site_hint(url: str, task: str) -> str:
    """Verilen URL için site-spesifik ipucu döndür."""
    for domain, info in _CATEGORY_KNOWLEDGE.items():
        if domain in url:
            hint = info.get("not", "")
            t = task.lower()
            for pattern, cat_url in info.get("categories", {}).items():
                if any(p in t for p in pattern.split("|")):
                    hint += f"\nDoğrudan bu URL'yi kullan: {cat_url}"
                    break
            return hint
    return ""

# Extension bağlantısı buradan yönetilir
_ext_ws = None          # aktif extension WebSocket bağlantısı
_pending: dict[str, asyncio.Future] = {}   # id → Future
_cmd_counter = 0


def set_extension_ws(ws):
    """server.py tarafından extension bağlandığında çağrılır."""
    global _ext_ws
    _ext_ws = ws


def clear_extension_ws():
    global _ext_ws
    _ext_ws = None


def extension_connected() -> bool:
    return _ext_ws is not None


async def send_command(action: str, params: dict = {}, timeout: float = 30.0) -> dict:
    """
    Extension'a komut gönder, yanıtını bekle.
    """
    global _cmd_counter
    if not _ext_ws:
        raise RuntimeError("Chrome eklentisi bağlı değil. Lütfen eklentiyi yükleyin.")

    _cmd_counter += 1
    cmd_id = str(_cmd_counter)

    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending[cmd_id] = fut

    try:
        await _ext_ws.send_text(json.dumps({"id": cmd_id, "action": action, "params": params}))
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    finally:
        _pending.pop(cmd_id, None)


def resolve_command(cmd_id: str, data: dict):
    """Extension'dan yanıt geldiğinde server.py tarafından çağrılır."""
    fut = _pending.get(cmd_id)
    if fut and not fut.done():
        fut.set_result(data)


# ─────────────────────────────────────────────────────────────────────────────

class BrowserExtAgent:
    """
    Atlas — Chrome eklentisi üzerinden browser kontrolü.
    Playwright YOK — kullanıcının kendi Chrome'u kullanılır.
    """

    def __init__(self):
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm    = create_llm(cfg["provider"], cfg["model"], temperature=0.2)
        self._label = f"{cfg['provider']}:{cfg['model']}"

    def refresh_llm(self):
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm    = create_llm(cfg["provider"], cfg["model"], temperature=0.2)
        self._label = f"{cfg['provider']}:{cfg['model']}"

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(
        self,
        task:              str,
        emit:              Emitter,
        approval_callback: Callable,
        context:           str = "",
    ) -> dict:
        if not extension_connected():
            await emit(wrap("browser.error", {
                "message": (
                    "Chrome eklentisi bağlı değil.\n"
                    "Lütfen static/extension klasörünü Chrome'a yükleyin:\n"
                    "chrome://extensions → Geliştirici modu → Paketlenmemiş yükle"
                )
            }))
            return {"success": False, "summary": "Eklenti bağlı değil.", "steps": []}

        await emit(wrap("browser.status", {"message": "🌐 Atlas Chrome'da yeni sekme açıyor..."}))

        result    = {"success": False, "summary": "", "steps": []}
        t_start   = time.perf_counter()
        tab_id    = None
        window_id = None

        try:
            # Ayrı pencerede yeni sekme aç (kullanıcının penceresini etkilemez)
            await emit(wrap("browser.status", {"message": "🪟 Atlas ayrı pencerede açılıyor..."}))
            resp      = await send_command("new_tab", {"url": "about:blank"})
            tab_id    = resp.get("tabId")
            window_id = resp.get("windowId")

            await emit(wrap("browser.status", {"message": "🧠 Atlas görevi planlıyor..."}))
            plan = await self._plan_task(task, context)

            summary, steps = await self._execute_plan(
                task, plan, emit, approval_callback, tab_id
            )

            result.update(success=True, summary=summary, steps=steps,
                          elapsed_s=round(time.perf_counter() - t_start, 1))

            # Final screenshot (arka planda — kullanıcıya dokunmaz)
            try:
                ss = await send_command("screenshot", {"tabId": tab_id}, timeout=10)
                if ss.get("image"):
                    await emit(wrap("browser.screenshot", {
                        "image": ss["image"],
                        "caption": "✅ Görev tamamlandı",
                        "final": True,
                    }))
            except Exception:
                pass

            # 3 saniye sonra pencereyi kapat
            await asyncio.sleep(3)
            try:
                await send_command("close_tab", {
                    "tabId": tab_id, "windowId": window_id
                })
            except Exception:
                pass

        except asyncio.CancelledError:
            result["summary"] = "Görev kullanıcı tarafından durduruldu."
            raise
        except Exception as e:
            result["summary"] = f"Hata: {e}"
            await emit(wrap("browser.error", {"message": str(e)}))

        await emit(wrap("browser.done", result))
        return result

    # ── Planlama ──────────────────────────────────────────────────────────────

    async def _plan_task(self, task: str, context: str) -> list[dict]:
        sites = _pick_sites(task)

        # Bilinen site uyarıları + kategori ipuçları
        known_warnings = ""
        for domain, info in _CATEGORY_KNOWLEDGE.items():
            t = task.lower()
            if domain.split(".")[0] in t or domain in t:
                known_warnings += f"\n⚠️  {domain}: {info.get('not', '')}"
                for pattern, cat_url in info.get("categories", {}).items():
                    if any(p.strip() in t for p in pattern.split("|")):
                        known_warnings += f"\n    ✅ Doğrudan bu URL'yi kullan: {cat_url}"
                        break

        site_hints = "\n".join(
            f"  - {s}: {_SITE_KNOWLEDGE.get(s,{}).get('search_url','').split('?')[0]}"
            for s in sites if _SITE_KNOWLEDGE.get(s, {}).get("search_url")
        )

        prompt = f"""You are Atlas, a smart browser automation agent running in the user's real Chrome.

TASK: {task}
{f"CONTEXT: {context[:400]}" if context else ""}

SITE WARNINGS — follow these exactly:
{known_warnings if known_warnings else "  (none)"}

RECOMMENDED SITES:
{site_hints if site_hints else "  Use Google to find the right site"}

AVAILABLE ACTIONS:
  navigate      → go to URL  (target = full https:// URL)
  nav_discover  → read ALL navigation links on current page → returns link texts + URLs
  nav_hover     → hover a nav item to reveal submenu, then read submenu links
                  (target = exact link text like "Aksesuar" or CSS selector)
  search        → use site's search box  (target = search query)
  click         → click element  (selector = CSS selector  OR  target = visible text)
  type          → type into focused input  (value = text)
  key           → keyboard key  (value = "Enter" / "Escape" / "ctrl+a" / "Tab")
  scroll        → scroll page  (value = "down" / "up" / number of pixels)
  screenshot    → take screenshot  (always use after navigate + after finding products)
  wait          → wait  (value = milliseconds as string, e.g. "2000")
  extract       → extract data from page text  (extract = what to get)
  done          → task complete  (description = Turkish summary of findings)

STEP FORMAT:
{{"action":"...","description":"Türkçe açıklama","target":"...","value":"...","selector":"...","extract":"...","needs_approval":false}}

STRATEGY — think through this:
1. If a WARNING+URL exists above → navigate directly there, skip search entirely
2. If no warning:
   a. Navigate to site homepage
   b. Run nav_discover to see the site's category structure
   c. If a matching category exists → navigate there
   d. If not → try site search; if search returns 0/wrong results → try nav_hover on relevant menu
3. After finding product listing page → extract names, prices, links
4. Always screenshot after each major navigation
5. needs_approval = true ONLY for: checkout/purchase/form submit/login/sending

Return ONLY a valid JSON array. No markdown, no explanation."""

        raw = _strip_think_blocks(
            await self.llm.generate([{"role": "user", "content": prompt}])
        )
        m = re.search(r'\[[\s\S]*\]', raw)
        if not m:
            return self._fallback_plan(task, sites)
        try:
            return json.loads(m.group())
        except Exception:
            return self._fallback_plan(task, sites)

    def _fallback_plan(self, task: str, sites: list[str]) -> list[dict]:
        """LLM başarısız olursa akıllı varsayılan plan."""
        q    = re.sub(r"(trendyol|hepsiburada|n11|amazon|dan|den|'dan|'den|asus|'dan)\s*", "", task, flags=re.I).strip() or task
        site = sites[0] if sites else "trendyol"
        url  = _build_search_url(site, q)

        # Bilinen uyarı var mı? (ör. ASUS arama çalışmaz)
        for domain, info in _CATEGORY_KNOWLEDGE.items():
            if domain.split(".")[0] in task.lower():
                for pattern, cat_url in info.get("categories", {}).items():
                    if any(p.strip() in task.lower() for p in pattern.split("|")):
                        return [
                            {"action": "navigate",
                             "description": f"Kategori sayfasına git",
                             "target": cat_url, "needs_approval": False},
                            {"action": "wait", "value": "2500",
                             "description": "Yükleniyor", "needs_approval": False},
                            {"action": "screenshot", "description": "Ürünlere bak", "needs_approval": False},
                            {"action": "extract", "extract": "product names and prices",
                             "description": "Ürünleri çıkar", "needs_approval": False},
                            {"action": "done", "description": "Tamamlandı", "needs_approval": False},
                        ]

        return [
            {"action": "navigate", "description": f"'{q}' aranıyor...",
             "target": url, "needs_approval": False},
            {"action": "wait", "value": "2500", "description": "Yükleniyor", "needs_approval": False},
            {"action": "screenshot", "description": "Sonuçlara bak", "needs_approval": False},
            {"action": "extract", "extract": "product names, prices, links",
             "description": "Ürünleri çıkar", "needs_approval": False},
            {"action": "done", "description": "Tamamlandı", "needs_approval": False},
        ]

    # ── Yürütme ───────────────────────────────────────────────────────────────

    async def _execute_plan(
        self,
        task: str,
        plan: list[dict],
        emit: Emitter,
        approval_callback: Callable,
        tab_id: int,
    ) -> tuple[str, list]:
        steps_done: list[dict] = []
        summary = ""
        # Extension'ın son bilinen fare konumu (Bezier için)
        mouse = {"x": 400.0, "y": 300.0}

        for i, step in enumerate(plan):
            action         = step.get("action", "screenshot")
            desc           = step.get("description", "")
            target         = step.get("target", "")
            value          = step.get("value", "")
            selector       = step.get("selector", "")
            needs_approval = step.get("needs_approval", False)

            await emit(wrap("browser.step", {
                "index": i, "total": len(plan),
                "action": action, "description": desc,
                "needs_approval": needs_approval,
            }))

            # Screenshot al
            try:
                ss_resp = await send_command("screenshot", {"tabId": tab_id}, timeout=10)
                ss_b64  = ss_resp.get("image")
            except Exception:
                ss_b64 = None
            if ss_b64:
                await emit(wrap("browser.screenshot", {"image": ss_b64, "caption": desc}))

            # Onay kontrolü
            if needs_approval:
                approved = await approval_callback(desc, ss_b64 or "")
                if not approved:
                    await emit(wrap("browser.status", {"message": f"⛔ Reddedildi: {desc}"}))
                    steps_done.append({"desc": desc, "status": "rejected"})
                    break

            try:
                res, mouse = await self._exec_step(
                    action, target, value, selector, step, tab_id, mouse
                )
                steps_done.append({"desc": desc, "status": "ok", "result": res})
                if action == "done":
                    summary = res or desc
                    if len(steps_done) > 2:
                        summary = await self._summarize(task, steps_done, tab_id)
            except Exception as e:
                await emit(wrap("browser.status", {"message": f"⚠️ Hata: {desc} — {e}"}))
                steps_done.append({"desc": desc, "status": "error", "error": str(e)})
                try:
                    ss2 = await send_command("screenshot", {"tabId": tab_id}, timeout=8)
                    if ss2.get("image"):
                        await emit(wrap("browser.screenshot", {
                            "image": ss2["image"], "caption": f"Hata: {desc}"
                        }))
                except Exception:
                    pass
                continue

        return summary or f"{task} tamamlandı.", steps_done

    async def _exec_step(
        self,
        action: str, target: str, value: str, selector: str,
        step: dict, tab_id: int, mouse: dict
    ) -> tuple[str, dict]:
        """Tek adımı çalıştır, yeni fare konumunu döndür."""

        # ── navigate ──
        if action == "navigate":
            url = target if target.startswith("http") else f"https://{target}"
            await send_command("navigate", {"tabId": tab_id, "url": url}, timeout=30)
            await asyncio.sleep(2.5)
            return f"Gidildi: {url}", mouse

        # ── nav_discover: sayfanın tüm nav linklerini oku ──
        elif action == "nav_discover":
            resp = await send_command("eval", {"tabId": tab_id, "code": """
(function() {
    const seen = new Set();
    const links = [];
    // Tüm nav/header linkleri topla
    const selectors = ['nav a', 'header a', '[role="navigation"] a',
                       '.navbar a', '.menu a', '.nav a', '#menu a',
                       '.header a', '.site-nav a', '.main-nav a'];
    const els = document.querySelectorAll(selectors.join(','));
    els.forEach(el => {
        const text = el.textContent.trim();
        const href = el.href;
        if (text && href && !seen.has(href) && href !== window.location.href) {
            seen.add(href);
            links.push(text + ' → ' + href);
        }
    });
    return links.slice(0, 60).join('\\n') || 'Navigasyon linki bulunamadı';
})()
            """}, timeout=10)
            nav_text = resp.get("result", "Navigasyon okunamadı")
            # LLM'e sor: hangi kategori URL'si göreve uygun?
            pick_prompt = (
                f"Görev: {step.get('_task', task)}\n\n"
                f"Sitede bulunan navigasyon linkleri:\n{nav_text}\n\n"
                f"Göreve en uygun kategori linkini seç ve sadece tam URL'yi yaz (başka hiçbir şey yazma)."
            )
            chosen = _strip_think_blocks(
                await self.llm.generate([{"role": "user", "content": pick_prompt}])
            ).strip()
            # URL mi döndü?
            url_match = re.search(r'https?://\S+', chosen)
            if url_match:
                chosen_url = url_match.group()
                await send_command("navigate", {"tabId": tab_id, "url": chosen_url}, timeout=30)
                await asyncio.sleep(2.5)
                return f"Kategori bulundu ve gidildi: {chosen_url}", mouse
            return f"Navigasyon linkleri:\n{nav_text[:500]}", mouse

        # ── nav_hover: menü öğesine hover et, alt menüyü oku ──
        elif action == "nav_hover":
            hover_target = selector or target
            # Önce elementi bul
            find_resp = await send_command("find_element", {
                "tabId": tab_id,
                "text": hover_target if not hover_target.startswith((".","#","[")) else None,
                "selector": hover_target if hover_target.startswith((".","#","[")) else None,
            }, timeout=6)

            if find_resp.get("found") and find_resp.get("coords"):
                c = find_resp["coords"]
                # Hover
                await send_command("mouse_move", {
                    "tabId": tab_id,
                    "fromX": mouse["x"], "fromY": mouse["y"],
                    "toX": c["x"], "toY": c["y"],
                }, timeout=8)
                mouse.update(x=c["x"], y=c["y"])
                await asyncio.sleep(0.8)  # Menünün açılmasını bekle

            # Submenu linklerini oku
            resp = await send_command("eval", {"tabId": tab_id, "code": """
(function() {
    // Görünür olan tüm linkleri al (hover sonrası görünür olanlar)
    const links = [];
    document.querySelectorAll('a').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            const text = el.textContent.trim();
            if (text && el.href) links.push(text + ' → ' + el.href);
        }
    });
    return links.slice(0, 40).join('\\n');
})()
            """}, timeout=8)
            submenu_text = resp.get("result", "")

            # LLM ile doğru linki seç
            pick_prompt = (
                f"Görev: {task}\n\n"
                f"Görünür linkler (hover sonrası):\n{submenu_text}\n\n"
                f"Göreve en uygun URL'yi seç ve sadece tam URL'yi yaz."
            )
            chosen = _strip_think_blocks(
                await self.llm.generate([{"role": "user", "content": pick_prompt}])
            ).strip()
            url_match = re.search(r'https?://\S+', chosen)
            if url_match:
                chosen_url = url_match.group()
                await send_command("navigate", {"tabId": tab_id, "url": chosen_url}, timeout=30)
                await asyncio.sleep(2.5)
                return f"Alt kategori seçildi: {chosen_url}", mouse
            return f"Submenu linkleri:\n{submenu_text[:400]}", mouse

        # ── search ──
        elif action == "search":
            query = target or value
            # Önce sayfada arama kutusu bulmayı dene
            candidates = [
                'input[type="search"]', 'input[name="q"]',
                'input[placeholder*="ara" i]', 'input[placeholder*="search" i]',
                '#searchInput', '#search-input', '[aria-label*="ara" i]',
                '[aria-label*="search" i]', 'input[type="text"]',
            ]
            found = False
            for sel in candidates:
                try:
                    fr = await send_command("find_element", {"tabId": tab_id, "selector": sel}, timeout=5)
                    if fr.get("found") and fr.get("coords"):
                        c = fr["coords"]
                        # Tıkla
                        await send_command("click", {
                            "tabId": tab_id, "x": c["x"], "y": c["y"],
                            "fromX": mouse["x"], "fromY": mouse["y"],
                        }, timeout=10)
                        mouse.update(x=c["x"], y=c["y"])
                        await asyncio.sleep(0.3)
                        # Temizle
                        await send_command("key", {"tabId": tab_id, "key": "ctrl+a"}, timeout=5)
                        await asyncio.sleep(0.1)
                        # Yaz
                        await send_command("type", {"tabId": tab_id, "text": query}, timeout=15)
                        await asyncio.sleep(0.4)
                        # Enter
                        await send_command("key", {"tabId": tab_id, "key": "Enter"}, timeout=5)
                        await asyncio.sleep(2.5)
                        found = True
                        break
                except Exception:
                    continue
            if not found:
                # Google'a düş
                url = f"https://www.google.com/search?q={query.replace(' ','+')}+site:{step.get('site','')}&hl=tr"
                await send_command("navigate", {"tabId": tab_id, "url": url}, timeout=30)
                await asyncio.sleep(2.5)
            return f"Arama: {query}", mouse

        # ── click ──
        elif action == "click":
            params: dict = {"tabId": tab_id, "fromX": mouse["x"], "fromY": mouse["y"]}
            if selector:
                params["selector"] = selector
            elif target:
                # Metin veya selector olabilir
                if target.startswith(("#",".","/","[","input","button","a")):
                    params["selector"] = target
                else:
                    params["text"] = target
            resp = await send_command("click", params, timeout=15)
            if resp.get("x"):
                mouse.update(x=resp["x"], y=resp["y"])
            await asyncio.sleep(1.5)
            return f"Tıklandı: {target or selector}", mouse

        # ── type ──
        elif action == "type":
            if selector or target:
                sel = selector or target
                fr = await send_command("find_element",
                    {"tabId": tab_id, "selector": sel}, timeout=5)
                if fr.get("found") and fr.get("coords"):
                    c = fr["coords"]
                    await send_command("click", {
                        "tabId": tab_id, "x": c["x"], "y": c["y"],
                        "fromX": mouse["x"], "fromY": mouse["y"],
                    }, timeout=10)
                    mouse.update(x=c["x"], y=c["y"])
                    await asyncio.sleep(0.3)
                    await send_command("key", {"tabId": tab_id, "key": "ctrl+a"}, timeout=5)
                    await asyncio.sleep(0.1)
            await send_command("type", {"tabId": tab_id, "text": value or ""}, timeout=20)
            return f"Yazıldı: {value}", mouse

        # ── key ──
        elif action == "key":
            await send_command("key", {"tabId": tab_id, "key": value or "Enter"}, timeout=5)
            await asyncio.sleep(0.5)
            return f"Tuş: {value}", mouse

        # ── scroll ──
        elif action == "scroll":
            direction = (value or "down").lower()
            delta = 500 if direction == "down" else -500
            await send_command("scroll", {"tabId": tab_id, "deltaY": delta}, timeout=8)
            await asyncio.sleep(0.8)
            return f"Kaydırıldı: {direction}", mouse

        # ── screenshot ──
        elif action == "screenshot":
            await asyncio.sleep(1.0)
            return "Screenshot alındı", mouse

        # ── wait ──
        elif action == "wait":
            ms = int(value) if str(value).isdigit() else 2000
            await asyncio.sleep(ms / 1000)
            return f"Beklendi: {ms}ms", mouse

        # ── extract ──
        elif action == "extract":
            await asyncio.sleep(2.0)  # İçerik yüklensin
            resp = await send_command("get_text", {"tabId": tab_id}, timeout=10)
            text = resp.get("text", "")[:4000]
            what = step.get("extract", "ürün adları ve fiyatlar")
            prompt = (
                f"Sayfa içeriğinden şunu çıkar: {what}\n\n"
                f"İçerik:\n{text}\n\n"
                "Kısa ve yapılandırılmış, Türkçe."
            )
            raw = await self.llm.generate([{"role": "user", "content": prompt}])
            return _strip_think_blocks(raw).strip(), mouse

        # ── done ──
        elif action == "done":
            return step.get("description", "Görev tamamlandı"), mouse

        else:
            return f"Bilinmeyen: {action}", mouse

    async def _summarize(self, task: str, steps: list, tab_id: int) -> str:
        steps_txt = "\n".join(
            f"- {s['desc']}: {s.get('result','')[:200]}"
            for s in steps if s.get("status") == "ok"
        )
        try:
            resp = await send_command("get_text", {"tabId": tab_id}, timeout=10)
            page_text = resp.get("text", "")[:2000]
        except Exception:
            page_text = ""
        prompt = (
            f"Görev: {task}\n\nAdımlar:\n{steps_txt}\n\n"
            f"Son sayfa:\n{page_text}\n\n"
            "Türkçe 3-4 cümle özet. Bulunanları vurgula."
        )
        raw = await self.llm.generate([{"role": "user", "content": prompt}])
        return _strip_think_blocks(raw).strip()
