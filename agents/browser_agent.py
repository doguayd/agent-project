"""
Browser Agent — Atlas
=====================
Playwright ile Chrome'u kontrol eden otomasyon ajanı.
Persona: Dikkatli, metodolojik bir araştırmacı-asistan.

Özellikler:
  - Sayfaları gezer, içerikleri okur, tıklar, form doldurur
  - Her önemli işlemden önce kullanıcıdan onay ister
  - Screenshot'ları UI'a stream eder (base64 PNG)
  - Hassas eylemler (submit/satın al/başvur) onay mekanizması ile korunur
  - Gemini Vision veya yerel model ile sayfa içeriğini analiz eder
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import Any, Callable

from config import MODELS, GOOGLE_API_KEY
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks

# Onay gerektiren eylem kalıpları
_APPROVAL_PATTERNS = [
    r'\bsubmit\b', r'\bapply\b', r'\bsend\b', r'\bbuy\b', r'\bpurchase\b',
    r'\bcheckout\b', r'\bpay\b', r'\bregister\b', r'\bsign.?up\b',
    r'\bconfirm\b', r'\bplace.?order\b', r'\bbaşvur\b', r'\bgönder\b',
    r'\bsatın.?al\b', r'\bkayıt\b', r'\bödeme\b', r'\bonay\b',
]


def _needs_approval(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in _APPROVAL_PATTERNS)


class BrowserAgent:
    """
    Atlas — web tarayıcısını kontrol eden ajan.

    approval_callback: Onay gerektiren eylem öncesi çağrılır.
    Coroutine olmalı, True döndürürse devam eder, False → durdurulur.
    """

    def __init__(self) -> None:
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm = create_llm(
            cfg["provider"], cfg["model"], temperature=0.2
        )
        self._label = f"{cfg['provider']}:{cfg['model']}"

    def refresh_llm(self) -> None:
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm = create_llm(cfg["provider"], cfg["model"], temperature=0.2)
        self._label = f"{cfg['provider']}:{cfg['model']}"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def run(
        self,
        task:              str,
        emit:              Emitter,
        approval_callback: Callable[[str, str], Any],  # (action_desc, screenshot_b64) → bool
        context:           str = "",
    ) -> dict:
        """
        Browser görevini çalıştır.
        approval_callback: async (action_desc: str, screenshot_b64: str) -> bool
        """
        await emit(wrap("browser.status", {"message": "🌐 Atlas tarayıcıyı başlatıyor..."}))

        from playwright.async_api import async_playwright

        result = {"success": False, "summary": "", "steps": []}
        t_start = time.perf_counter()

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=False,
                    args=["--start-maximized"],
                )
                context_pw = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    locale="tr-TR",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page = await context_pw.new_page()

                # Wrap page actions with screenshot emitter
                ctx = _PageContext(
                    page=page,
                    emit=emit,
                    approval_callback=approval_callback,
                    llm=self.llm,
                    label=self._label,
                )

                # Generate & execute the plan
                await emit(wrap("browser.status", {"message": "🧠 Atlas görevi planlıyor..."}))
                plan = await self._plan_task(task, context, ctx)
                summary, steps = await self._execute_plan(task, plan, ctx)

                result["success"] = True
                result["summary"] = summary
                result["steps"]   = steps
                result["elapsed_s"] = round(time.perf_counter() - t_start, 1)

                # Final screenshot
                ss = await ctx.screenshot()
                if ss:
                    await emit(wrap("browser.screenshot", {
                        "image":   ss,
                        "caption": "✅ Görev tamamlandı",
                        "final":   True,
                    }))

                await asyncio.sleep(2)
                await browser.close()

        except asyncio.CancelledError:
            result["summary"] = "Görev kullanıcı tarafından durduruldu."
            raise
        except Exception as e:
            result["summary"] = f"Hata: {e}"
            await emit(wrap("browser.error", {"message": str(e)}))

        await emit(wrap("browser.done", result))
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Planning
    # ─────────────────────────────────────────────────────────────────────────

    async def _plan_task(
        self, task: str, context: str, ctx: "_PageContext"
    ) -> list[dict]:
        """LLM'e görev ver, adımları JSON olarak al."""
        prompt = f"""You are Atlas, a browser automation assistant.
Your job is to create a STEP-BY-STEP browser automation plan.

TASK (may be in Turkish or English): {task}
{f"CONTEXT: {context[:400]}" if context else ""}

Create a JSON plan. Each step has:
  - "action": one of navigate|click|type|scroll|screenshot|search|wait|extract|done
  - "description": brief Turkish description of what this step does (shown to user)
  - "target": URL (for navigate), selector/text (for click/type), query (for search)
  - "value": text to type (for type action) or scroll direction (up/down/px)
  - "needs_approval": true if this step does something irreversible (submit, buy, apply, send)
  - "extract": what data to extract from the page (for extract action)

IMPORTANT RULES:
1. For search tasks (e.g. "n11'den mavi ayakkabı bul"), navigate to the site then search
2. For job applications, navigate to the career page, find positions, prepare to apply
3. Always take a screenshot after major steps
4. Mark needs_approval=true for: form submissions, purchases, applications, logins
5. End with a "done" action summarizing what was found/done
6. Keep steps minimal and focused — quality over quantity

Respond ONLY with valid JSON array:
[
  {{"action": "navigate", "description": "...", "target": "https://...", "needs_approval": false}},
  {{"action": "screenshot", "description": "Sayfayı kontrol et", "needs_approval": false}},
  ...
  {{"action": "done", "description": "Görev tamamlandı: ...", "needs_approval": false}}
]"""

        raw = await self.llm.generate([{"role": "user", "content": prompt}])
        raw = _strip_think_blocks(raw)

        # Parse JSON array
        m = re.search(r'\[[\s\S]*\]', raw)
        if not m:
            # Fallback: simple plan
            return [
                {"action": "navigate",    "description": f"{task} için web'e gidiliyor",
                 "target": "https://www.google.com/search?q=" + task.replace(" ", "+"),
                 "needs_approval": False},
                {"action": "screenshot",  "description": "Sonuçları görüntüle", "needs_approval": False},
                {"action": "done",        "description": "Arama tamamlandı", "needs_approval": False},
            ]
        try:
            return json.loads(m.group())
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_plan(
        self, task: str, plan: list[dict], ctx: "_PageContext"
    ) -> tuple[str, list]:
        steps_done: list[dict] = []
        summary = ""

        for i, step in enumerate(plan):
            action = step.get("action", "screenshot")
            desc   = step.get("description", "")
            target = step.get("target", "")
            value  = step.get("value", "")
            needs_approval = step.get("needs_approval", False) or _needs_approval(desc)

            # Emit current step
            await ctx.emit(wrap("browser.step", {
                "index": i,
                "total": len(plan),
                "action": action,
                "description": desc,
                "needs_approval": needs_approval,
            }))

            # Take screenshot before approval check
            ss_b64 = await ctx.screenshot()
            if ss_b64:
                await ctx.emit(wrap("browser.screenshot", {
                    "image":   ss_b64,
                    "caption": desc,
                }))

            # Approval check
            if needs_approval:
                approved = await ctx.approval_callback(desc, ss_b64 or "")
                if not approved:
                    await ctx.emit(wrap("browser.status", {
                        "message": f"⛔ Adım kullanıcı tarafından reddedildi: {desc}"
                    }))
                    steps_done.append({"desc": desc, "status": "rejected"})
                    break

            # Execute action
            try:
                step_result = await ctx.execute(action, target, value, step)
                steps_done.append({"desc": desc, "status": "ok", "result": step_result})

                if action == "done":
                    summary = step_result or desc
                    # If we have extracted content, use LLM to generate nice summary
                    if len(steps_done) > 2:
                        summary = await self._summarize(task, steps_done, ctx)

            except Exception as e:
                await ctx.emit(wrap("browser.status", {
                    "message": f"⚠️ Adım hatası: {desc} — {e}"
                }))
                steps_done.append({"desc": desc, "status": "error", "error": str(e)})
                # Try to recover with a screenshot
                ss_b64 = await ctx.screenshot()
                if ss_b64:
                    await ctx.emit(wrap("browser.screenshot", {
                        "image":   ss_b64,
                        "caption": f"Hata sonrası durum: {desc}",
                    }))
                continue

        if not summary:
            summary = f"{task} görevi tamamlandı."
        return summary, steps_done

    async def _summarize(self, task: str, steps: list, ctx: "_PageContext") -> str:
        """Tamamlanan adımları Türkçe özetle."""
        steps_txt = "\n".join(
            f"- {s['desc']}: {s.get('result','')[:200]}"
            for s in steps if s.get("status") == "ok"
        )
        # Get page content for context
        page_text = await ctx.get_page_text(max_chars=2000)
        prompt = f"""Görev: {task}

Tamamlanan adımlar:
{steps_txt}

Sayfadan alınan içerik (son sayfa):
{page_text}

Kullanıcıya Türkçe kısa bir özet yaz. Ne bulduğunu, ne yaptığını özetle.
3-4 cümle yeterli. Sonuçları vurgula."""

        raw = await self.llm.generate([{"role": "user", "content": prompt}])
        return _strip_think_blocks(raw).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Page Context Helper
# ─────────────────────────────────────────────────────────────────────────────

class _PageContext:
    """Playwright page üzerinde yardımcı metodlar."""

    def __init__(self, page, emit: Emitter, approval_callback, llm, label: str):
        self.page              = page
        self.emit              = emit
        self.approval_callback = approval_callback
        self.llm               = llm
        self.label             = label

    async def screenshot(self) -> str | None:
        """Sayfa screenshot'ını base64 PNG döndür."""
        try:
            data = await self.page.screenshot(type="png", full_page=False)
            return base64.b64encode(data).decode()
        except Exception:
            return None

    async def get_page_text(self, max_chars: int = 3000) -> str:
        """Sayfanın görünür metin içeriğini al."""
        try:
            text = await self.page.evaluate("""
                () => {
                    const body = document.body;
                    const walker = document.createTreeWalker(
                        body, NodeFilter.SHOW_TEXT, null
                    );
                    const texts = [];
                    let node;
                    while (node = walker.nextNode()) {
                        const t = node.textContent.trim();
                        if (t.length > 2) texts.push(t);
                    }
                    return texts.join(' ').slice(0, 5000);
                }
            """)
            return (text or "")[:max_chars]
        except Exception:
            return ""

    async def execute(
        self, action: str, target: str, value: str, step: dict
    ) -> str:
        """Bir adımı çalıştır, sonucu string olarak döndür."""
        page = self.page

        if action == "navigate":
            url = target if target.startswith("http") else f"https://{target}"
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(1500)
            return f"Gidildi: {url}"

        elif action == "search":
            # Google veya sayfa içi arama
            query = target or value
            if not page.url or "about:blank" in page.url:
                await page.goto(
                    f"https://www.google.com/search?q={query.replace(' ','+')}&hl=tr",
                    wait_until="domcontentloaded", timeout=20000
                )
            else:
                # Sayfada arama kutusu bul
                searched = False
                for sel in [
                    'input[type="search"]', 'input[name="q"]',
                    'input[placeholder*="ara"]', 'input[placeholder*="search"]',
                    '#search', '.search-input', '[data-testid="search"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        await el.fill(query, timeout=3000)
                        await el.press("Enter")
                        searched = True
                        break
                    except Exception:
                        continue
                if not searched:
                    await page.goto(
                        f"https://www.google.com/search?q={query.replace(' ','+')}&hl=tr",
                        wait_until="domcontentloaded", timeout=20000
                    )
            await page.wait_for_timeout(2000)
            return f"Arama yapıldı: {query}"

        elif action == "click":
            # Önce selector, yoksa metin ile bul
            clicked = False
            if target:
                for sel in [target, f'text="{target}"', f"text={target}"]:
                    try:
                        el = page.locator(sel).first
                        await el.scroll_into_view_if_needed(timeout=3000)
                        await el.click(timeout=5000)
                        clicked = True
                        break
                    except Exception:
                        continue
            if not clicked:
                raise RuntimeError(f"Tıklanacak element bulunamadı: {target}")
            await page.wait_for_timeout(1000)
            return f"Tıklandı: {target}"

        elif action == "type":
            sel = target or 'input:visible'
            try:
                el = page.locator(sel).first
                await el.fill(value or "", timeout=5000)
            except Exception:
                await page.keyboard.type(value or "")
            return f"Yazıldı: {value}"

        elif action == "scroll":
            direction = (value or "down").lower()
            px = 600 if direction == "down" else -600
            await page.evaluate(f"window.scrollBy(0, {px})")
            await page.wait_for_timeout(500)
            return f"Kaydırıldı: {direction}"

        elif action == "extract":
            text = await self.get_page_text(max_chars=4000)
            what = step.get("extract", "bilgi")
            # Ask LLM to extract specific info
            prompt = f"""Sayfa içeriğinden şunu çıkar: {what}

Sayfa içeriği:
{text}

Kısa, yapılandırılmış bir cevap ver. Türkçe."""
            raw = await self.llm.generate([{"role": "user", "content": prompt}])
            return _strip_think_blocks(raw).strip()

        elif action == "screenshot":
            return "Screenshot alındı"

        elif action == "wait":
            ms = int(value) if value and value.isdigit() else 2000
            await page.wait_for_timeout(ms)
            return f"Beklendi: {ms}ms"

        elif action == "done":
            return step.get("description", "Görev tamamlandı")

        else:
            return f"Bilinmeyen eylem: {action}"
