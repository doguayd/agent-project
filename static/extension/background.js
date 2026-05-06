/**
 * Atlas Extension — Background Service Worker
 * ============================================
 * - Atlas görevlerini AYRI BİR PENCEREDE çalıştırır (kullanıcının penceresine dokunmaz)
 * - CDP Page.captureScreenshot ile ARKA PLANDA screenshot (sekme aktif olmak zorunda değil)
 * - CDP Input.dispatchMouseEvent ile insan gibi fare hareketi
 * - navigator.webdriver gizlenir (bot koruması azaltılır)
 */

const SERVER_WS    = "ws://localhost:8000/ws/atlas-ext";
const RECONNECT_MS = 1000;   // Hızlı yeniden bağlantı (SW cold-start için)

let ws             = null;
let activeTabId    = null;   // Atlas'ın kontrol ettiği sekme
let activeWindowId = null;   // Atlas'ın ayrı penceresi
let debuggerTabs   = new Set();  // Debugger bağlı sekmeler

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  ws = new WebSocket(SERVER_WS);

  ws.onopen  = ()  => { console.log("[Atlas] Bağlandı."); sendMsg({ type: "ext.connected", version: "1.1" }); };
  ws.onmessage = async (e) => { try { await handleCommand(JSON.parse(e.data)); } catch {} };
  ws.onclose = ()  => { console.log("[Atlas] Kesildi, yeniden bağlanıyor..."); setTimeout(connect, RECONNECT_MS); };
  ws.onerror = (e) => console.error("[Atlas] WS hata:", e);
}

function sendMsg(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// ── Komut işleyici ────────────────────────────────────────────────────────────

async function handleCommand(cmd) {
  const { id, action, params = {} } = cmd;
  const reply = (data)  => sendMsg({ type: "ext.result", id, action, ...data });
  const error = (msg)   => sendMsg({ type: "ext.error",  id, action, error: msg });

  try {
    switch (action) {

      // ── Ayrı pencerede yeni sekme aç ──
      case "new_tab": {
        // Kullanıcının penceresinden bağımsız, focused:false → kullanıcı etkilenmez
        const win = await chrome.windows.create({
          url:     params.url || "about:blank",
          focused: false,        // ← kullanıcının penceresini çalmaz
          state:   "normal",
          width:   1366,
          height:  800,
          left:    50,
          top:     50,
        });
        activeWindowId = win.id;
        activeTabId    = win.tabs[0].id;

        await waitForTabLoad(activeTabId);
        await injectStealth(activeTabId);
        reply({ tabId: activeTabId, windowId: activeWindowId, url: win.tabs[0].url });
        break;
      }

      // ── Sekmeye git (aktif yapmadan) ──
      case "navigate": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await chrome.tabs.update(tabId, { url: params.url });
        // active: true YAPMA — kullanıcının odağını çalma
        await waitForTabLoad(tabId);
        await injectStealth(tabId);
        const tab = await chrome.tabs.get(tabId);
        reply({ url: tab.url, tabId });
        break;
      }

      // ── Arka plan screenshot (CDP — sekme aktif olmak zorunda değil!) ──
      case "screenshot": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }

        await ensureDebugger(tabId);
        try {
          // Page.captureScreenshot — arka planda çalışır, sekmeyi öne getirmez
          const result = await sendCDP(tabId, "Page.captureScreenshot", {
            format:  "png",
            quality: 85,
            captureBeyondViewport: false,
          });
          reply({ image: result.data, tabId });
        } catch (e) {
          // Fallback: sekmeyi geçici aktif yap (sadece Atlas penceresi)
          await chrome.windows.update(activeWindowId, { focused: true }).catch(() => {});
          await chrome.tabs.update(tabId, { active: true });
          await sleep(150);
          const dataUrl = await chrome.tabs.captureVisibleTab(activeWindowId, { format: "png" });
          // Kullanıcının penceresini tekrar öne al
          const [userWin] = await chrome.windows.getAll({ windowTypes: ["normal"] });
          // Eski pencereye odaklanma (Atlas penceresi dışındaki ilk pencere)
          const wins = await chrome.windows.getAll({ windowTypes: ["normal"] });
          const userWindow = wins.find(w => w.id !== activeWindowId);
          if (userWindow) await chrome.windows.update(userWindow.id, { focused: true });
          reply({ image: dataUrl.split(",")[1], tabId });
        }
        break;
      }

      // ── Sayfa metni ──
      case "get_text": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const results = await chrome.scripting.executeScript({
          target: { tabId },
          func: () => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
            const parts = [];
            let n;
            while (n = walker.nextNode()) { const t = n.textContent.trim(); if (t.length > 2) parts.push(t); }
            return {
              text:  parts.join(" ").slice(0, 8000),
              title: document.title || "",
              url:   location.href  || "",
            };
          },
        });
        const r = results[0]?.result || {};
        reply({ text: r.text || "", title: r.title || "", url: r.url || "" });
        break;
      }

      // ── URL ──
      case "get_url": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const tab = await chrome.tabs.get(tabId);
        reply({ url: tab.url, tabId });
        break;
      }

      // ── İnsan gibi fare hareketi (CDP — arka planda çalışır) ──
      case "mouse_move": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);
        const path = humanPath(params.fromX || 400, params.fromY || 300, params.toX, params.toY);
        for (const pt of path) {
          await sendCDP(tabId, "Input.dispatchMouseEvent", {
            type: "mouseMoved", x: Math.round(pt.x), y: Math.round(pt.y), modifiers: 0,
          });
          await sleep(pt.delay);
        }
        reply({ ok: true });
        break;
      }

      // ── Tıkla (CDP — arka planda) ──
      case "click": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }

        let x = params.x, y = params.y;

        if ((!x || !y) && params.selector) {
          const coords = await getElementCenter(tabId, params.selector);
          if (!coords) { error(`Element bulunamadı: ${params.selector}`); break; }
          x = coords.x; y = coords.y;
        }
        if ((!x || !y) && params.text) {
          const coords = await getElementCenterByText(tabId, params.text);
          if (!coords) { error(`Metin bulunamadı: ${params.text}`); break; }
          x = coords.x; y = coords.y;
        }
        if (!x || !y) { error("Koordinat veya selector gerekli"); break; }

        await ensureDebugger(tabId);

        // İnsan gibi hareket
        const path = humanPath(params.fromX || 400, params.fromY || 300, x, y);
        for (const pt of path) {
          await sendCDP(tabId, "Input.dispatchMouseEvent", {
            type: "mouseMoved", x: Math.round(pt.x), y: Math.round(pt.y), modifiers: 0,
          });
          await sleep(pt.delay);
        }

        await sleep(randomBetween(60, 180));
        await sendCDP(tabId, "Input.dispatchMouseEvent", { type: "mousePressed", button: "left", x: Math.round(x), y: Math.round(y), clickCount: 1 });
        await sleep(randomBetween(40, 100));
        await sendCDP(tabId, "Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", x: Math.round(x), y: Math.round(y), clickCount: 1 });

        reply({ ok: true, x, y });
        break;
      }

      // ── Yaz (CDP — arka planda) ──
      case "type": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);
        for (const ch of (params.text || "")) {
          await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "char", text: ch });
          const d = randomBetween(50, 140) + (Math.random() < 0.07 ? randomBetween(200, 500) : 0);
          await sleep(d);
        }
        reply({ ok: true, typed: params.text?.length || 0 });
        break;
      }

      // ── Klavye tuşu ──
      case "key": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);
        const keyMap = {
          "Enter": "Return", "Escape": "Escape", "Tab": "Tab",
          "ctrl+a": null,  // özel handle
          "ctrl+c": null,
        };
        const key = params.key || "Enter";
        if (key === "ctrl+a") {
          await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "keyDown", key: "a", modifiers: 2 });
          await sleep(50);
          await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "keyUp",   key: "a", modifiers: 2 });
        } else {
          await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "keyDown", key });
          await sleep(50);
          await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "keyUp",   key });
        }
        reply({ ok: true });
        break;
      }

      // ── Scroll (CDP — arka planda) ──
      case "scroll": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);
        const deltaY = params.deltaY || 400;
        const steps  = randomBetween(4, 7);
        for (let i = 0; i < steps; i++) {
          await sendCDP(tabId, "Input.dispatchMouseEvent", {
            type: "mouseWheel",
            x: randomBetween(400, 900), y: randomBetween(200, 500),
            deltaX: 0, deltaY: Math.round(deltaY / steps) + randomBetween(-10, 10),
          });
          await sleep(randomBetween(80, 200));
        }
        reply({ ok: true });
        break;
      }

      // ── Element bul ──
      case "find_element": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const coords = params.selector
          ? await getElementCenter(tabId, params.selector)
          : await getElementCenterByText(tabId, params.text);
        reply({ found: !!coords, coords });
        break;
      }

      // ── JS çalıştır ──
      // ÖNEMLI: new Function(code) → dış fonksiyon return yapmaz, sonuç undefined olur!
      // Doğru: new Function("return " + code) → IIFE'nin dönüş değerini iletir.
      case "eval": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const results = await chrome.scripting.executeScript({
          target: { tabId },
          func:   new Function("return (" + params.code + ")"),
        });
        reply({ result: results[0]?.result });
        break;
      }

      // ── Sekme kapat ──
      case "close_tab": {
        const tabId    = params.tabId    || activeTabId;
        const windowId = params.windowId || activeWindowId;
        if (tabId && debuggerTabs.has(tabId)) {
          try { await chrome.debugger.detach({ tabId }); } catch {}
          debuggerTabs.delete(tabId);
        }
        // Pencereyi kapat (içindeki sekme de kapanır)
        if (windowId) {
          try { await chrome.windows.remove(windowId); } catch {}
          if (activeWindowId === windowId) { activeWindowId = null; activeTabId = null; }
        } else if (tabId) {
          try { await chrome.tabs.remove(tabId); } catch {}
          if (activeTabId === tabId) activeTabId = null;
        }
        reply({ ok: true });
        break;
      }

      // ── Durum sorgusu (popup) ──
      case "get.status":
        reply({ connected: true });
        break;

      default:
        error(`Bilinmeyen: ${action}`);
    }
  } catch (e) {
    error(`Hata: ${e.message || e}`);
  }
}

// ── Stealth Enjeksiyonu ────────────────────────────────────────────────────────

async function injectStealth(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        // navigator.webdriver gizle
        Object.defineProperty(navigator, "webdriver", { get: () => undefined });

        // Chrome runtime simüle et
        if (!window.chrome) window.chrome = {};
        if (!window.chrome.runtime) window.chrome.runtime = {};

        // Gerçekçi dil
        Object.defineProperty(navigator, "languages", { get: () => ["tr-TR","tr","en-US","en"] });

        // Permissions — bot kontrolünü engelle
        if (navigator.permissions?.query) {
          const orig = navigator.permissions.query.bind(navigator.permissions);
          navigator.permissions.query = p =>
            p.name === "notifications"
              ? Promise.resolve({ state: Notification.permission, onchange: null })
              : orig(p);
        }
      },
      world: "MAIN",   // sayfanın kendi JS ortamında çalış
    });
  } catch {}
}

// ── Debugger ─────────────────────────────────────────────────────────────────

async function ensureDebugger(tabId) {
  if (debuggerTabs.has(tabId)) return;
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    debuggerTabs.add(tabId);
    // Page domain'i etkinleştir (screenshot için gerekli)
    await chrome.debugger.sendCommand({ tabId }, "Page.enable", {});
    // Stealth: automation flag'i kaldır
    try {
      await chrome.debugger.sendCommand({ tabId }, "Page.addScriptToEvaluateOnNewDocument", {
        source: `Object.defineProperty(navigator,'webdriver',{get:()=>undefined});`
      });
    } catch {}
  } catch (e) {
    if (!e.message?.includes("already")) throw e;
    debuggerTabs.add(tabId);
  }
}

function sendCDP(tabId, method, params = {}) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params, result => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(result || {});
    });
  });
}

chrome.debugger.onDetach.addListener((src) => {
  if (src.tabId) debuggerTabs.delete(src.tabId);
});

// ── Yardımcılar ───────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function randomBetween(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a; }

async function waitForTabLoad(tabId, timeout = 25000) {
  return new Promise(resolve => {
    const start = Date.now();
    const check = () => {
      chrome.tabs.get(tabId, tab => {
        if (chrome.runtime.lastError || Date.now() - start > timeout) { resolve(); return; }
        if (tab.status === "complete") { resolve(); return; }
        setTimeout(check, 200);
      });
    };
    check();
  });
}

async function getElementCenter(tabId, selector) {
  try {
    const r = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        const rect = el.getBoundingClientRect();
        if (rect.width === 0) return null;
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      },
      args: [selector],
    });
    return r[0]?.result || null;
  } catch { return null; }
}

async function getElementCenterByText(tabId, text) {
  try {
    const r = await chrome.scripting.executeScript({
      target: { tabId },
      func: (txt) => {
        const lower = txt.toLowerCase();
        const all   = [...document.querySelectorAll("a,button,input,label,span,div,li,h1,h2,h3")];
        const el    = all.find(e =>
          e.textContent.trim().toLowerCase().includes(lower) ||
          e.getAttribute?.("aria-label")?.toLowerCase().includes(lower) ||
          e.getAttribute?.("placeholder")?.toLowerCase().includes(lower)
        );
        if (!el) return null;
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        const rect = el.getBoundingClientRect();
        if (rect.width === 0) return null;
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      },
      args: [text],
    });
    return r[0]?.result || null;
  } catch { return null; }
}

// ── Bezier fare yolu ─────────────────────────────────────────────────────────

function humanPath(x0, y0, x1, y1) {
  const dist  = Math.hypot(x1 - x0, y1 - y0);
  const steps = Math.max(15, Math.min(60, Math.floor(dist / 12)));
  const dev   = dist * 0.28;
  const cp1   = { x: x0 + (x1-x0)*0.25 + (Math.random()-.5)*2*dev, y: y0 + (y1-y0)*0.25 + (Math.random()-.5)*2*dev };
  const cp2   = { x: x0 + (x1-x0)*0.75 + (Math.random()-.5)*2*dev, y: y0 + (y1-y0)*0.75 + (Math.random()-.5)*2*dev };
  const path  = [];
  for (let i = 0; i <= steps; i++) {
    const t  = i / steps;
    const te = t * t * (3 - 2 * t);
    const u  = 1 - te;
    path.push({
      x: u**3*x0 + 3*u**2*te*cp1.x + 3*u*te**2*cp2.x + te**3*x1,
      y: u**3*y0 + 3*u**2*te*cp1.y + 3*u*te**2*cp2.y + te**3*y1,
      delay: randomBetween(6, 20),
    });
  }
  return path;
}

// ── Service Worker Keepalive (MV3'te SW 30s sonra ölür — alarm ile canlı tut) ──
chrome.alarms.create("atlas-keepalive", { periodInMinutes: 0.17 }); // her ~10s — SW'yi uyanık tut
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "atlas-keepalive") {
    // SW'yi canlı tutan boş işlem
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      connect();
    }
    // Aktif sekme varsa ping at
    if (activeTabId) {
      chrome.tabs.get(activeTabId, () => { chrome.runtime.lastError; }); // hata yoksay
    }
  }
});

// ── Başlat ────────────────────────────────────────────────────────────────────
connect();
