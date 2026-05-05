"""
Browser Agent — Atlas
=====================
Playwright ile tarayıcıyı kontrol eden otomasyon ajanı.

Strateji (bot tespitini azaltmak için):
  1. Öncelik: Kullanıcının gerçek Chrome profili (çerezler + oturum)
  2. Yedek  : Firefox (Cloudflare/DataDome Firefox'u daha az bloke eder)
  3. Son çare: Playwright Chromium + playwright-stealth

  - İnsan gibi Bezier eğrisi fare hareketi
  - Her sayfada networkidle veya içerik yüklenene kadar akıllı bekleme
  - Warm-up: hedef siteye gitmeden önce Google'da kısa ön gezinti
  - Hassas eylemler onay ile korunur
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import random
import re
import shutil
import tempfile
import time
from typing import Any, Callable

from config import MODELS
from core.events import Emitter, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks

# ── Onay kalıpları ───────────────────────────────────────────────────────────
_APPROVAL_PATTERNS = [
    r'\bsubmit\b', r'\bapply\b', r'\bsend\b', r'\bbuy\b', r'\bpurchase\b',
    r'\bcheckout\b', r'\bpay\b', r'\bregister\b', r'\bsign.?up\b',
    r'\bconfirm\b', r'\bplace.?order\b', r'\bbaşvur\b', r'\bgönder\b',
    r'\bsatın.?al\b', r'\bkayıt\b', r'\bödeme\b', r'\bonay\b',
]

def _needs_approval(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in _APPROVAL_PATTERNS)

# ── Chrome profil yolu ───────────────────────────────────────────────────────
_CHROME_USER_DATA = os.path.expanduser("~/AppData/Local/Google/Chrome/User Data")

# ── Kapsamlı stealth JS ──────────────────────────────────────────────────────
_STEALTH_JS = """
// 1) webdriver gizle
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2) Chrome runtime
window.chrome = { runtime: {}, loadTimes: () => ({}), csi: () => ({}), app: {} };

// 3) Gerçekçi plugin listesi
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        function fakePlugin(name, fn, desc, mimes) {
            const p = Object.create(Plugin.prototype);
            Object.defineProperties(p, {
                name: { get: () => name },
                filename: { get: () => fn },
                description: { get: () => desc },
                length: { get: () => mimes.length },
            });
            mimes.forEach((m, i) => { p[i] = m; });
            return p;
        }
        return [
            fakePlugin('Chrome PDF Plugin','internal-pdf-viewer','PDF',
                [{ type:'application/x-google-chrome-pdf', suffixes:'pdf', description:'PDF' }]),
            fakePlugin('Chrome PDF Viewer','mhjfbmdgcfjbbpaeojofohoefgiehjai','',
                [{ type:'application/pdf', suffixes:'pdf', description:'' }]),
        ];
    }
});

// 4) Dil
Object.defineProperty(navigator, 'languages', { get: () => ['tr-TR','tr','en-US','en'] });

// 5) Ekran
try {
    Object.defineProperty(screen,'colorDepth',{ get:()=>24 });
    Object.defineProperty(screen,'pixelDepth',{ get:()=>24 });
} catch(_){}

// 6) Permissions
if (navigator.permissions && navigator.permissions.query) {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = p =>
        p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission, onchange: null })
            : origQuery(p);
}

// 7) Canvas gürültüsü
(function(){
    const orig = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type,...args){
        const ctx2d = this.getContext('2d');
        if (ctx2d) {
            const px = ctx2d.getImageData(0,0,1,1);
            px.data[0] ^= Math.random() < 0.5 ? 1 : 0;
            ctx2d.putImageData(px,0,0);
        }
        return orig.apply(this,[type,...args]);
    };
})();

// 8) WebRTC — yerel IP sızıntısı engelle
if (window.RTCPeerConnection) {
    const Orig = window.RTCPeerConnection;
    window.RTCPeerConnection = function(cfg,...a){
        if (cfg && cfg.iceServers) cfg.iceServers = [];
        return new Orig(cfg,...a);
    };
    window.RTCPeerConnection.prototype = Orig.prototype;
}

// 9) Battery
if (navigator.getBattery)
    navigator.getBattery = () => Promise.resolve({
        charging:true, chargingTime:0, dischargingTime:Infinity, level:1,
        addEventListener:()=>{}, removeEventListener:()=>{},
    });

// 10) Connection
try {
    Object.defineProperty(navigator,'connection',{
        get:()=>({ effectiveType:'4g', rtt:45, downlink:15, saveData:false,
                   addEventListener:()=>{}, removeEventListener:()=>{} }),
    });
} catch(_){}
"""

# ── Bezier fare hareketi ─────────────────────────────────────────────────────
def _bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (
        u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0],
        u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1],
    )

def _human_path(start, end, steps=40):
    sx,sy = start; ex,ey = end
    dist = math.hypot(ex-sx, ey-sy)
    d = dist * 0.3
    p1 = (sx+(ex-sx)*.25+random.uniform(-d,d), sy+(ey-sy)*.25+random.uniform(-d,d))
    p2 = (sx+(ex-sx)*.75+random.uniform(-d,d), sy+(ey-sy)*.75+random.uniform(-d,d))
    path = []
    for i in range(steps+1):
        t = i/steps
        te = t*t*(3-2*t)  # ease-in-out
        path.append(_bezier((sx,sy),p1,p2,(ex,ey),te))
    return path


# ─────────────────────────────────────────────────────────────────────────────
class BrowserAgent:
    """Atlas — tarayıcı otomasyon ajanı."""

    def __init__(self):
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm    = create_llm(cfg["provider"], cfg["model"], temperature=0.2)
        self._label = f"{cfg['provider']}:{cfg['model']}"

    def refresh_llm(self):
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm    = create_llm(cfg["provider"], cfg["model"], temperature=0.2)
        self._label = f"{cfg['provider']}:{cfg['model']}"

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self, task: str, emit: Emitter,
                  approval_callback: Callable, context: str = "") -> dict:

        await emit(wrap("browser.status", {"message": "🌐 Atlas tarayıcıyı başlatıyor..."}))

        from playwright.async_api import async_playwright

        # playwright-stealth
        try:
            from playwright_stealth.stealth import Stealth
            _stealth = Stealth()
        except Exception:
            _stealth = None

        result  = {"success": False, "summary": "", "steps": []}
        t_start = time.perf_counter()

        try:
            async with async_playwright() as pw:
                browser, ctx_pw, page = await self._launch(pw, emit, _stealth)

                pctx = _PageContext(
                    page=page, emit=emit,
                    approval_callback=approval_callback,
                    llm=self.llm, label=self._label,
                    stealth=_stealth,
                )

                # Warm-up: kısa Google gezintisi (güven skoru için)
                await self._warmup(pctx, emit)

                await emit(wrap("browser.status", {"message": "🧠 Atlas görevi planlıyor..."}))
                plan = await self._plan_task(task, context, pctx)
                summary, steps = await self._execute_plan(task, plan, pctx)

                result.update(success=True, summary=summary, steps=steps,
                              elapsed_s=round(time.perf_counter()-t_start,1))

                ss = await pctx.screenshot()
                if ss:
                    await emit(wrap("browser.screenshot",
                                   {"image":ss,"caption":"✅ Görev tamamlandı","final":True}))

                await asyncio.sleep(2)
                await ctx_pw.close()
                if browser:
                    await browser.close()

        except asyncio.CancelledError:
            result["summary"] = "Görev kullanıcı tarafından durduruldu."
            raise
        except Exception as e:
            result["summary"] = f"Hata: {e}"
            await emit(wrap("browser.error", {"message": str(e)}))

        await emit(wrap("browser.done", result))
        return result

    # ── Tarayıcı başlatma stratejisi ─────────────────────────────────────────

    async def _launch(self, pw, emit, stealth):
        """
        Önce gerçek Chrome profili ile dene.
        Başarısız olursa Firefox ile dene.
        Son çare Playwright Chromium.
        """
        # ── Strateji 1: Gerçek Chrome profili ──
        if os.path.isdir(_CHROME_USER_DATA):
            try:
                profile_copy = await asyncio.get_event_loop().run_in_executor(
                    None, self._copy_profile
                )
                await emit(wrap("browser.status",{
                    "message":"👤 Chrome profili yükleniyor (gerçek çerezler aktif)..."
                }))
                ctx_pw = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile_copy,
                    headless=False,
                    channel="chrome",
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                        "--lang=tr-TR,tr,en-US,en",
                        "--no-first-run",
                        "--disable-extensions-except=",
                    ],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1366, "height": 768},
                    locale="tr-TR",
                    timezone_id="Europe/Istanbul",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={"Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8"},
                )
                await ctx_pw.add_init_script(_STEALTH_JS)
                page = ctx_pw.pages[0] if ctx_pw.pages else await ctx_pw.new_page()
                if stealth:
                    try: await stealth.apply_stealth_async(page)
                    except Exception: pass
                return None, ctx_pw, page
            except Exception as e:
                await emit(wrap("browser.status",{
                    "message":f"⚠️ Chrome profili açılamadı ({e}), Firefox deneniyor..."
                }))

        # ── Strateji 2: Firefox ──
        try:
            await emit(wrap("browser.status",{"message":"🦊 Firefox ile bağlanıyor..."}))
            browser = await pw.firefox.launch(
                headless=False,
                args=["--width=1366","--height=768"],
            )
            ctx_pw = await browser.new_context(
                viewport={"width":1366,"height":768},
                locale="tr-TR",
                timezone_id="Europe/Istanbul",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
                    "Gecko/20100101 Firefox/125.0"
                ),
                extra_http_headers={"Accept-Language":"tr-TR,tr;q=0.9,en-US;q=0.8"},
            )
            # Firefox için hafif stealth (webdriver gizle)
            await ctx_pw.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            page = await ctx_pw.new_page()
            return browser, ctx_pw, page
        except Exception as e:
            await emit(wrap("browser.status",{
                "message":f"⚠️ Firefox başlatılamadı ({e}), Chromium deneniyor..."
            }))

        # ── Strateji 3: Playwright Chromium + stealth ──
        await emit(wrap("browser.status",{"message":"🌐 Stealth Chromium başlatılıyor..."}))
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--lang=tr-TR,tr,en-US,en",
                "--no-first-run",
            ],
            ignore_default_args=["--enable-automation"],
        )
        ctx_pw = await browser.new_context(
            viewport={"width":1366,"height":768},
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language":"tr-TR,tr;q=0.9,en-US;q=0.8"},
        )
        await ctx_pw.add_init_script(_STEALTH_JS)
        page = await ctx_pw.new_page()
        if stealth:
            try: await stealth.apply_stealth_async(page)
            except Exception: pass
        return browser, ctx_pw, page

    def _copy_profile(self) -> str:
        """
        Chrome profil dizinini geçici konuma kopyala.
        (Chrome açıkken kilitleme sorununu önler.)
        Sadece kritik dosyaları kopyala — tam kopya çok büyük.
        """
        tmp = tempfile.mkdtemp(prefix="atlas_chrome_")
        src = _CHROME_USER_DATA
        default_src = os.path.join(src, "Default")
        default_dst = os.path.join(tmp, "Default")

        if os.path.isdir(default_src):
            # Sadece çerez ve oturum dosyalarını kopyala
            os.makedirs(default_dst, exist_ok=True)
            for fname in ["Cookies","Login Data","Web Data","Preferences","Secure Preferences"]:
                s = os.path.join(default_src, fname)
                d = os.path.join(default_dst, fname)
                if os.path.isfile(s):
                    try:
                        shutil.copy2(s, d)
                    except Exception:
                        pass
        return tmp

    # ── Warm-up ───────────────────────────────────────────────────────────────

    async def _warmup(self, pctx: "_PageContext", emit: Emitter):
        """Hedef siteye gitmeden önce Google'da 5-8 saniye geç."""
        try:
            await emit(wrap("browser.status",{"message":"🔥 Warm-up: Google gezintisi..."}))
            await pctx.page.goto(
                "https://www.google.com.tr/?hl=tr",
                wait_until="domcontentloaded", timeout=15000
            )
            await asyncio.sleep(random.uniform(2.0, 3.5))
            # Biraz scroll + fare hareketi
            await pctx._idle_move()
            await asyncio.sleep(random.uniform(0.8, 1.5))
            await pctx.page.evaluate("window.scrollBy({top:200,behavior:'smooth'})")
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await pctx._idle_move()
        except Exception:
            pass  # Warm-up başarısız olsa da devam et

    # ── Planlama ──────────────────────────────────────────────────────────────

    async def _plan_task(self, task, context, ctx) -> list[dict]:
        prompt = f"""You are Atlas, a browser automation assistant.
Create a minimal STEP-BY-STEP plan for:

TASK: {task}
{f"CONTEXT: {context[:400]}" if context else ""}

Each step is a JSON object:
  "action": navigate|click|type|scroll|screenshot|search|wait|extract|done
  "description": short Turkish description
  "target": URL / CSS selector / search query
  "value": text to type or scroll pixels
  "needs_approval": true ONLY for submit/buy/apply/login/send
  "extract": what to extract (for extract action)

RULES:
- navigate directly to the most relevant page (not homepage if possible)
- search within site if needed
- always take screenshot after each major action
- wait at least 2000ms after navigation before screenshot
- use extract to get product names, prices, info
- end with done action

Return ONLY a valid JSON array."""

        raw = _strip_think_blocks(await self.llm.generate([{"role":"user","content":prompt}]))
        m = re.search(r'\[[\s\S]*\]', raw)
        if not m:
            return [
                {"action":"navigate","description":"Arama sayfasına git",
                 "target":f"https://www.google.com/search?q={task.replace(' ','+')}",
                 "needs_approval":False},
                {"action":"wait","value":"3000","description":"Sayfa yüklensin","needs_approval":False},
                {"action":"screenshot","description":"Sonuçlara bak","needs_approval":False},
                {"action":"done","description":"Tamamlandı","needs_approval":False},
            ]
        try:
            return json.loads(m.group())
        except Exception:
            return []

    # ── Yürütme ───────────────────────────────────────────────────────────────

    async def _execute_plan(self, task, plan, ctx):
        steps_done = []
        summary    = ""

        for i, step in enumerate(plan):
            action         = step.get("action","screenshot")
            desc           = step.get("description","")
            target         = step.get("target","")
            value          = step.get("value","")
            needs_approval = step.get("needs_approval",False) or _needs_approval(desc)

            await ctx.emit(wrap("browser.step",{
                "index":i,"total":len(plan),
                "action":action,"description":desc,
                "needs_approval":needs_approval,
            }))

            ss_b64 = await ctx.screenshot()
            if ss_b64:
                await ctx.emit(wrap("browser.screenshot",{"image":ss_b64,"caption":desc}))

            if needs_approval:
                approved = await ctx.approval_callback(desc, ss_b64 or "")
                if not approved:
                    await ctx.emit(wrap("browser.status",{"message":f"⛔ Reddedildi: {desc}"}))
                    steps_done.append({"desc":desc,"status":"rejected"})
                    break

            try:
                res = await ctx.execute(action, target, value, step)
                steps_done.append({"desc":desc,"status":"ok","result":res})
                if action == "done":
                    summary = res or desc
                    if len(steps_done) > 2:
                        summary = await self._summarize(task, steps_done, ctx)
            except Exception as e:
                await ctx.emit(wrap("browser.status",{"message":f"⚠️ Hata: {desc} — {e}"}))
                steps_done.append({"desc":desc,"status":"error","error":str(e)})
                ss_b64 = await ctx.screenshot()
                if ss_b64:
                    await ctx.emit(wrap("browser.screenshot",{
                        "image":ss_b64,"caption":f"Hata sonrası: {desc}"
                    }))
                continue

        return summary or f"{task} tamamlandı.", steps_done

    async def _summarize(self, task, steps, ctx) -> str:
        steps_txt = "\n".join(
            f"- {s['desc']}: {s.get('result','')[:200]}"
            for s in steps if s.get("status")=="ok"
        )
        page_text = await ctx.get_page_text(max_chars=2000)
        prompt = f"Görev: {task}\n\nAdımlar:\n{steps_txt}\n\nSon sayfa:\n{page_text}\n\nTürkçe 3-4 cümle özet."
        raw = await self.llm.generate([{"role":"user","content":prompt}])
        return _strip_think_blocks(raw).strip()


# ─────────────────────────────────────────────────────────────────────────────
class _PageContext:

    def __init__(self, page, emit, approval_callback, llm, label, stealth=None):
        self.page              = page
        self.emit              = emit
        self.approval_callback = approval_callback
        self.llm               = llm
        self.label             = label
        self._stealth          = stealth
        self._mx = float(random.randint(400, 900))
        self._my = float(random.randint(200, 500))

    # ── İnsan fare ───────────────────────────────────────────────────────────

    async def human_move(self, x, y):
        dist  = math.hypot(x-self._mx, y-self._my)
        if dist < 2: return
        steps = max(15, min(70, int(dist/10)))
        jit   = dist * 0.012
        for pt in _human_path((self._mx,self._my),(x,y),steps=steps):
            await self.page.mouse.move(
                pt[0]+random.uniform(-jit,jit),
                pt[1]+random.uniform(-jit,jit),
            )
            await asyncio.sleep(random.uniform(0.006,0.020))
        self._mx, self._my = x, y

    async def human_click(self, x, y):
        await self.human_move(x, y)
        await asyncio.sleep(random.uniform(0.05, 0.18))
        await self.page.mouse.click(x, y)
        await asyncio.sleep(random.uniform(0.08, 0.22))

    async def human_type(self, text: str):
        for ch in text:
            await self.page.keyboard.type(ch)
            d = random.uniform(0.05, 0.14)
            if random.random() < 0.07: d += random.uniform(0.2, 0.5)
            await asyncio.sleep(d)

    async def _idle_move(self):
        x = max(20, min(1340, self._mx+random.uniform(-120,120)))
        y = max(20, min(740,  self._my+random.uniform(-80, 80)))
        await self.human_move(x, y)

    # ── Akıllı bekleme ───────────────────────────────────────────────────────

    async def _wait_for_content(self, timeout_ms: int = 8000):
        """
        Sayfa boş değil gerçek içerik yüklenene kadar bekle.
        Hem networkidle hem de body text kontrolü.
        """
        page = self.page
        deadline = time.time() + timeout_ms/1000

        # networkidle dene
        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 6000))
        except Exception:
            pass

        # Body text kontrolü — en az 200 karakter olana kadar bekle
        while time.time() < deadline:
            try:
                txt_len = await page.evaluate(
                    "document.body ? document.body.innerText.trim().length : 0"
                )
                if txt_len > 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)
            await self._idle_move()

        # Son bekleme — dinamik render için
        await asyncio.sleep(random.uniform(1.0, 2.0))

    # ── Temel araçlar ─────────────────────────────────────────────────────────

    async def screenshot(self) -> str | None:
        try:
            data = await self.page.screenshot(type="png", full_page=False)
            return base64.b64encode(data).decode()
        except Exception:
            return None

    async def get_page_text(self, max_chars=3000) -> str:
        try:
            text = await self.page.evaluate("""
                () => {
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT, null
                    );
                    const parts = [];
                    let n;
                    while (n = walker.nextNode()) {
                        const t = n.textContent.trim();
                        if (t.length > 2) parts.push(t);
                    }
                    return parts.join(' ').slice(0, 7000);
                }
            """)
            return (text or "")[:max_chars]
        except Exception:
            return ""

    async def _center(self, locator) -> tuple | None:
        try:
            box = await locator.bounding_box(timeout=4000)
            if box:
                return (box["x"]+box["width"]/2, box["y"]+box["height"]/2)
        except Exception:
            pass
        return None

    # ── Eylem yürütücü ────────────────────────────────────────────────────────

    async def execute(self, action: str, target: str, value: str, step: dict) -> str:
        page = self.page

        # ── navigate ──
        if action == "navigate":
            url = target if target.startswith("http") else f"https://{target}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass  # Timeout olsa da devam et
            await self._wait_for_content(8000)
            await self._idle_move()
            return f"Gidildi: {url}"

        # ── search ──
        elif action == "search":
            query = target or value
            if not page.url or "about:blank" in page.url:
                await page.goto(
                    f"https://www.google.com/search?q={query.replace(' ','+')}",
                    wait_until="domcontentloaded", timeout=30000
                )
                await self._wait_for_content(6000)
            else:
                # Sayfa içi arama
                candidates = [
                    'input[type="search"]', 'input[name="q"]',
                    'input[placeholder*="ara" i]', 'input[placeholder*="search" i]',
                    '#searchInput','#search-input','.search-input',
                    '[aria-label*="ara" i]','[aria-label*="search" i]',
                    'input[type="text"]',
                ]
                searched = False
                for sel in candidates:
                    try:
                        el = page.locator(sel).first
                        if not await el.is_visible(timeout=2000):
                            continue
                        await el.scroll_into_view_if_needed(timeout=3000)
                        c = await self._center(el)
                        if c:
                            await self.human_click(*c)
                            await asyncio.sleep(random.uniform(0.3, 0.6))
                            await page.keyboard.press("ctrl+a")
                            await asyncio.sleep(0.1)
                            await self.human_type(query)
                            await asyncio.sleep(random.uniform(0.4, 0.8))
                            await page.keyboard.press("Enter")
                            searched = True
                            break
                    except Exception:
                        continue
                if not searched:
                    # Google'a düş
                    await page.goto(
                        f"https://www.google.com/search?q={query.replace(' ','+')}",
                        wait_until="domcontentloaded", timeout=30000
                    )
                await self._wait_for_content(8000)
                await self._idle_move()
            return f"Arama: {query}"

        # ── click ──
        elif action == "click":
            clicked = False
            for sel in [target, f'text="{target}"', f"text={target}"]:
                try:
                    el = page.locator(sel).first
                    if not await el.is_visible(timeout=2000): continue
                    await el.scroll_into_view_if_needed(timeout=3000)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                    c = await self._center(el)
                    if c:
                        await self.human_click(*c)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                try:
                    el = page.locator(target).first
                    await el.scroll_into_view_if_needed(timeout=3000)
                    await el.click(timeout=5000)
                    clicked = True
                except Exception:
                    raise RuntimeError(f"Element bulunamadı: {target}")
            await self._wait_for_content(5000)
            return f"Tıklandı: {target}"

        # ── type ──
        elif action == "type":
            sel = target or "input:visible"
            try:
                el = page.locator(sel).first
                c  = await self._center(el)
                if c: await self.human_click(*c)
                await page.keyboard.press("ctrl+a")
                await asyncio.sleep(0.1)
                await self.human_type(value or "")
            except Exception:
                await self.human_type(value or "")
            return f"Yazıldı: {value}"

        # ── scroll ──
        elif action == "scroll":
            direction = (value or "down").lower()
            total     = 700 if direction=="down" else -700
            chunks    = random.randint(4, 7)
            for _ in range(chunks):
                px = total//chunks + random.randint(-20,20)
                await page.evaluate(f"window.scrollBy({{top:{px},left:0,behavior:'smooth'}})")
                await asyncio.sleep(random.uniform(0.12, 0.30))
            await asyncio.sleep(random.uniform(0.4, 0.9))
            return f"Kaydırıldı: {direction}"

        # ── extract ──
        elif action == "extract":
            await self._wait_for_content(5000)
            text = await self.get_page_text(max_chars=4000)
            what = step.get("extract", "ürün adları ve fiyatlar")
            prompt = (
                f"Sayfa içeriğinden şunu çıkar: {what}\n\n"
                f"İçerik:\n{text}\n\n"
                "Kısa ve yapılandırılmış, Türkçe."
            )
            raw = await self.llm.generate([{"role":"user","content":prompt}])
            return _strip_think_blocks(raw).strip()

        # ── screenshot ──
        elif action == "screenshot":
            await self._wait_for_content(4000)
            return "Screenshot alındı"

        # ── wait ──
        elif action == "wait":
            ms      = int(value) if value and str(value).isdigit() else 2000
            wait_s  = ms / 1000
            elapsed = 0.0
            while elapsed < wait_s:
                chunk = random.uniform(0.4, 1.0)
                await asyncio.sleep(min(chunk, wait_s-elapsed))
                elapsed += chunk
                if elapsed < wait_s and random.random() < 0.4:
                    await self._idle_move()
            return f"Beklendi: {ms}ms"

        # ── done ──
        elif action == "done":
            return step.get("description", "Görev tamamlandı")

        else:
            return f"Bilinmeyen eylem: {action}"
