/**
 * Atlas Extension — Background Service Worker
 * ============================================
 * Sunucuya WebSocket ile bağlanır.
 * Sunucudan gelen komutları Chrome API'leri ile çalıştırır.
 * Sonuçları (screenshot, sayfa metni, vb.) sunucuya geri gönderir.
 */

const SERVER_WS = "ws://localhost:8000/ws/atlas-ext";
const RECONNECT_MS = 3000;

let ws = null;
let activeTabId = null;  // Atlas'ın şu an kontrol ettiği sekme
let debuggerAttached = false;

// ── WebSocket Bağlantısı ─────────────────────────────────────────────────────

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  ws = new WebSocket(SERVER_WS);

  ws.onopen = () => {
    console.log("[Atlas] Sunucuya bağlandı.");
    sendMsg({ type: "ext.connected", version: "1.0" });
  };

  ws.onmessage = async (event) => {
    let cmd;
    try { cmd = JSON.parse(event.data); } catch { return; }
    await handleCommand(cmd);
  };

  ws.onclose = () => {
    console.log("[Atlas] Bağlantı kesildi, yeniden bağlanılıyor...");
    setTimeout(connect, RECONNECT_MS);
  };

  ws.onerror = (e) => console.error("[Atlas] WS hata:", e);
}

function sendMsg(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

// ── Komut İşleyici ────────────────────────────────────────────────────────────

async function handleCommand(cmd) {
  const { id, action, params = {} } = cmd;

  const reply = (data) => sendMsg({ type: "ext.result", id, action, ...data });
  const error = (msg)  => sendMsg({ type: "ext.error",  id, action, error: msg });

  try {
    switch (action) {

      // ── Yeni sekme aç ──
      case "new_tab": {
        const tab = await chrome.tabs.create({ url: params.url || "about:blank", active: true });
        activeTabId = tab.id;
        await waitForTabLoad(tab.id);
        reply({ tabId: tab.id, url: tab.url });
        break;
      }

      // ── Sekmeye git ──
      case "navigate": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await chrome.tabs.update(tabId, { url: params.url });
        await waitForTabLoad(tabId);
        activeTabId = tabId;
        const tab = await chrome.tabs.get(tabId);
        reply({ url: tab.url, tabId });
        break;
      }

      // ── Screenshot ──
      case "screenshot": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        // Sekmeyi aktif yap (captureVisibleTab için şart)
        await chrome.tabs.update(tabId, { active: true });
        await sleep(200);
        const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: "png" });
        // "data:image/png;base64," önekini çıkar
        const b64 = dataUrl.split(",")[1];
        reply({ image: b64, tabId });
        break;
      }

      // ── Sayfa metni ──
      case "get_text": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const results = await chrome.scripting.executeScript({
          target: { tabId },
          func: () => {
            const walker = document.createTreeWalker(
              document.body, NodeFilter.SHOW_TEXT, null
            );
            const parts = [];
            let n;
            while (n = walker.nextNode()) {
              const t = n.textContent.trim();
              if (t.length > 2) parts.push(t);
            }
            return parts.join(" ").slice(0, 8000);
          },
        });
        reply({ text: results[0]?.result || "" });
        break;
      }

      // ── Sayfa URL ──
      case "get_url": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const tab = await chrome.tabs.get(tabId);
        reply({ url: tab.url, tabId });
        break;
      }

      // ── İnsan gibi fare hareketi (CDP) ──
      case "mouse_move": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);
        const path = humanPath(
          params.fromX || 400, params.fromY || 300,
          params.toX, params.toY
        );
        for (const pt of path) {
          await sendCDP(tabId, "Input.dispatchMouseEvent", {
            type: "mouseMoved",
            x: Math.round(pt.x), y: Math.round(pt.y),
            modifiers: 0,
          });
          await sleep(pt.delay);
        }
        reply({ ok: true });
        break;
      }

      // ── İnsan gibi tıklama ──
      case "click": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }

        // Önce elementi bul, koordinatını al
        let x = params.x, y = params.y;
        if (!x && params.selector) {
          const coords = await getElementCenter(tabId, params.selector);
          if (!coords) { error(`Element bulunamadı: ${params.selector}`); break; }
          x = coords.x; y = coords.y;
        }
        if (!x && params.text) {
          const coords = await getElementCenterByText(tabId, params.text);
          if (!coords) { error(`Metin bulunamadı: ${params.text}`); break; }
          x = coords.x; y = coords.y;
        }

        await ensureDebugger(tabId);

        // İnsan gibi hareket
        const path = humanPath(params.fromX || 400, params.fromY || 300, x, y);
        for (const pt of path) {
          await sendCDP(tabId, "Input.dispatchMouseEvent", {
            type: "mouseMoved", x: Math.round(pt.x), y: Math.round(pt.y), modifiers: 0,
          });
          await sleep(pt.delay);
        }

        // Tıklamadan önce kısa duraklama
        await sleep(randomBetween(60, 180));

        await sendCDP(tabId, "Input.dispatchMouseEvent", {
          type: "mousePressed", button: "left",
          x: Math.round(x), y: Math.round(y),
          clickCount: 1, modifiers: 0,
        });
        await sleep(randomBetween(40, 100));
        await sendCDP(tabId, "Input.dispatchMouseEvent", {
          type: "mouseReleased", button: "left",
          x: Math.round(x), y: Math.round(y),
          clickCount: 1, modifiers: 0,
        });

        reply({ ok: true, x, y });
        break;
      }

      // ── İnsan gibi yazma ──
      case "type": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);

        const text = params.text || "";
        for (const ch of text) {
          await sendCDP(tabId, "Input.dispatchKeyEvent", {
            type: "char", text: ch,
          });
          const delay = randomBetween(50, 140) + (Math.random() < 0.07 ? randomBetween(200,500) : 0);
          await sleep(delay);
        }
        reply({ ok: true, typed: text.length });
        break;
      }

      // ── Klavye tuşu ──
      case "key": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        await ensureDebugger(tabId);
        const key = params.key || "Enter";
        await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "keyDown", key });
        await sleep(50);
        await sendCDP(tabId, "Input.dispatchKeyEvent", { type: "keyUp", key });
        reply({ ok: true });
        break;
      }

      // ── Scroll ──
      case "scroll": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const deltaY = params.deltaY || 400;
        const steps  = randomBetween(4, 7);
        await ensureDebugger(tabId);
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

      // ── Element var mı ──
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
      case "eval": {
        const tabId = params.tabId || activeTabId;
        if (!tabId) { error("Sekme yok"); break; }
        const results = await chrome.scripting.executeScript({
          target: { tabId },
          func: new Function(params.code),
        });
        reply({ result: results[0]?.result });
        break;
      }

      // ── Sekme kapat ──
      case "close_tab": {
        const tabId = params.tabId || activeTabId;
        if (tabId) {
          if (debuggerAttached) {
            try { await chrome.debugger.detach({ tabId }); } catch {}
            debuggerAttached = false;
          }
          await chrome.tabs.remove(tabId);
          if (activeTabId === tabId) activeTabId = null;
        }
        reply({ ok: true });
        break;
      }

      default:
        error(`Bilinmeyen komut: ${action}`);
    }
  } catch (e) {
    error(`Hata: ${e.message || e}`);
  }
}

// ── Yardımcı Fonksiyonlar ─────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function randomBetween(a, b) {
  return Math.floor(Math.random() * (b - a + 1)) + a;
}

async function waitForTabLoad(tabId, timeout = 20000) {
  return new Promise((resolve) => {
    const start = Date.now();
    const check = () => {
      chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError || Date.now() - start > timeout) {
          resolve(); return;
        }
        if (tab.status === "complete") { resolve(); return; }
        setTimeout(check, 200);
      });
    };
    check();
  });
}

async function ensureDebugger(tabId) {
  if (!debuggerAttached) {
    try {
      await chrome.debugger.attach({ tabId }, "1.3");
      debuggerAttached = true;
    } catch (e) {
      // Zaten bağlı olabilir
      if (!e.message.includes("already")) throw e;
      debuggerAttached = true;
    }
  }
}

function sendCDP(tabId, method, params = {}) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params, (result) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(result);
    });
  });
}

async function getElementCenter(tabId, selector) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        const rect = el.getBoundingClientRect();
        return { x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
      },
      args: [selector],
    });
    return results[0]?.result || null;
  } catch { return null; }
}

async function getElementCenterByText(tabId, text) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: (txt) => {
        const lower = txt.toLowerCase();
        const all = [...document.querySelectorAll("a,button,input,label,span,div,li")];
        const el = all.find(e =>
          e.textContent.trim().toLowerCase().includes(lower) ||
          e.getAttribute("aria-label")?.toLowerCase().includes(lower) ||
          e.getAttribute("placeholder")?.toLowerCase().includes(lower)
        );
        if (!el) return null;
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        const rect = el.getBoundingClientRect();
        return { x: rect.left + rect.width/2, y: rect.top + rect.height/2 };
      },
      args: [text],
    });
    return results[0]?.result || null;
  } catch { return null; }
}

// ── İnsan gibi Bezier yolu ────────────────────────────────────────────────────

function humanPath(x0, y0, x1, y1) {
  const dist = Math.hypot(x1-x0, y1-y0);
  const steps = Math.max(15, Math.min(60, Math.floor(dist/12)));
  const dev = dist * 0.28;

  const cp1 = {
    x: x0 + (x1-x0)*0.25 + (Math.random()-0.5)*2*dev,
    y: y0 + (y1-y0)*0.25 + (Math.random()-0.5)*2*dev,
  };
  const cp2 = {
    x: x0 + (x1-x0)*0.75 + (Math.random()-0.5)*2*dev,
    y: y0 + (y1-y0)*0.75 + (Math.random()-0.5)*2*dev,
  };

  const path = [];
  for (let i = 0; i <= steps; i++) {
    const t  = i / steps;
    const te = t * t * (3 - 2*t);  // ease-in-out
    const u  = 1 - te;
    path.push({
      x: u**3*x0 + 3*u**2*te*cp1.x + 3*u*te**2*cp2.x + te**3*x1,
      y: u**3*y0 + 3*u**2*te*cp1.y + 3*u*te**2*cp2.y + te**3*y1,
      delay: randomBetween(6, 20),
    });
  }
  return path;
}

// ── Debugger detach event ─────────────────────────────────────────────────────
chrome.debugger.onDetach.addListener(() => {
  debuggerAttached = false;
});

// ── Başlat ───────────────────────────────────────────────────────────────────
connect();
