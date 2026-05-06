# Atlas — Geliştirici Notları & Öğrenilen Dersler

Bu dosya, geliştirme sürecinde keşfedilen kritik hatalar, çözümler ve dikkat edilmesi gereken
mimari kararları belgeler. Gelecekteki geliştirmeler için referans olarak kullanılmalıdır.

---

## 🐛 Bilinen Hatalar & Çözümler

### 0. ace-step — Python 3.14'te çalışmıyor
**Sorun:** `pip install ace-step` → `spacy==3.8.4` için Python 3.14 wheel yok.  
**Çözüm:** Meta **MusicGen** kullan (`transformers` + `accelerate` + `scipy`).  
**Kurulum:**
```bash
pip install transformers accelerate scipy
# CUDA için (RTX 4090):
pip install torch --index-url https://download.pytorch.org/whl/cu128 --force-reinstall
```
**Kalite:** MusicGen-medium ACE-Step'e yakın kalite, daha iyi Python uyumu.  
**Model:** `facebook/musicgen-medium` (~1.5GB, ilk kullanımda indirilir).  
**Hız RTX 4090:** 30s müzik ≈ 20-30s üretim süresi.

---

### 1. `new Function(code)` — eval sonucu undefined döner
**Dosya:** `static/extension/background.js` → `case "eval"`  
**Sorun:**
```javascript
// YANLIŞ — dış fonksiyon return içermiyor, sonuç undefined!
func: new Function(params.code)
// code = "(function() { return links; })()"
// Üretilen kod: function anonymous() { (function() { return links; })() }
// → dış fonksiyon return yapmıyor → undefined
```
**Çözüm:**
```javascript
// DOĞRU — return ile sarmala
func: new Function("return (" + params.code + ")")
```
**Etki:** `nav_discover` ve `nav_hover` aksiyonları hep boş sonuç alıyordu; navigasyon çalışmıyordu.

---

### 2. `get_text` — CAPTCHA tespiti için title eksik
**Dosya:** `static/extension/background.js` → `case "get_text"`  
**Sorun:** Sadece `text` döndürüyordu, `document.title` döndürmüyordu.  
**Çözüm:** `{ text, title, url }` döndür:
```javascript
return {
  text:  parts.join(" ").slice(0, 8000),
  title: document.title || "",
  url:   location.href  || "",
};
```
**Etki:** `_check_captcha()` her zaman `title=""` alıyordu, Cloudflare "Just a Moment" sayfasını atlaması mümkün değildi.

---

### 3. MV3 Service Worker — 30s sonra ölüyor
**Dosya:** `static/extension/background.js`, `static/extension/manifest.json`  
**Sorun:** Chrome MV3 service worker'ı 30s inaktivite sonrası öldürür. Extension bağlantısı kesilir, reconnect 3s sürer, toplam yeniden bağlanma 30s+ alabilir.  
**Çözüm:**
```javascript
// manifest.json'a "alarms" permission ekle
// background.js'de keepalive alarm:
chrome.alarms.create("atlas-keepalive", { periodInMinutes: 0.17 }); // her ~10s
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "atlas-keepalive") {
    if (!ws || ws.readyState === WebSocket.CLOSED) connect();
    if (activeTabId) chrome.tabs.get(activeTabId, () => { chrome.runtime.lastError; });
  }
});
```
**Dikkat:** `periodInMinutes` minimum değeri Chrome'da ~0.1 (yaklaşık 6s). 0.17 = ~10s.

---

### 4. Race Condition — Extension Playwright'tan önce bağlanamıyor
**Dosya:** `server.py` → `_get_browser_agent()`  
**Sorun:** Kullanıcı görev gönderdiğinde extension henüz bağlanmamış olabilir (server yeni başlamış, SW yeni uyandı). Eski kod direkt Playwright'a geçiyordu.  
**Çözüm:** `_get_browser_agent()` async yapıldı, 12s bekler:
```python
async def _get_browser_agent():
    if extension_connected():
        return browser_ext
    for i in range(24):        # 24 × 0.5s = 12s
        await asyncio.sleep(0.5)
        if extension_connected():
            return browser_ext
    return browser_agt         # Playwright fallback
```
**Neden 12s:** SW cold-start ~5-10s + reconnect 1s + buffer = 12s.

---

### 5. Extension Güncelleme Sonrası Manuel Reload Gerekir
**Sorun:** `background.js` değiştirildiğinde Chrome eski SW'yi çalıştırmaya devam eder.  
**Çözüm:** `chrome://extensions` → Atlas → 🔄 (yenile butonuna bas).  
**Belirti:** Server'da `"Atlas Chrome eklentisi bağlandı"` logu görünmüyor, extension bağlı değil.

---

### 6. Extension Bağlantı Sorunu Teşhisi
Extension bağlanmıyorsa sırayla kontrol et:
1. `chrome://extensions` → Atlas extension aktif mi?
2. Service Worker "Çalışıyor" mu? (Click "service worker" link)
3. Service worker konsolunda hata var mı?
4. Server çalışıyor mu? (`http://localhost:8000/health`)
5. Server logu: `"Atlas Chrome eklentisi bağlandı"` görünüyor mu?
6. Extension güncellenmiş mi? → chrome://extensions → Yeniden Yükle

---

### 7. ASUS Türkiye Arama Sorunu
**Sorun:** `www.asus.com/tr/search?q=...` → `searchType=news` parametresi ekler → ürün değil haber döndürür.  
**Çözüm:** ASUS TR'de doğrudan kategori URL'lerini kullan:
- Çanta: `https://www.asus.com/tr/accessories/apparel-bags-and-gear/`
- ROG Çanta: `https://www.asus.com/tr/accessories/apparel-bags-and-gear/rog--republic-of-gamers/`
- Doğru URL: `/accessories/apparel-bags-and-gear/` (NOT `/accessories/bags-and-cases/` — 404 verir!)

---

### 8. Bot Koruması — Çok Katmanlı Yaklaşım
Extension modu gerçek Chrome kullandığı için en güvenli. Sıralama:
1. **Chrome Extension (en iyi):** Kullanıcının gerçek Chrome'u, gerçek çerezler, gerçek profil
2. **CDP stealth:** `navigator.webdriver = undefined`, canvas fingerprint, WebRTC block
3. **Bezier curve mouse:** İnsan gibi kavisli fare hareketi, rastgele gecikmeler
4. **Playwright fallback (en kötü):** Bot tespitine çok açık

---

### 9. screenshot — Sekmeyi Aktif Yapmadan (CDP)
**Sorun:** `chrome.tabs.captureVisibleTab()` sekmenin aktif ve pencereyin odaklanmış olmasını gerektirir → kullanıcının penceresini çalar.  
**Çözüm:** CDP `Page.captureScreenshot` ile arka planda:
```javascript
await chrome.debugger.attach({ tabId }, "1.3");
await chrome.debugger.sendCommand({ tabId }, "Page.enable", {});
const result = await sendCDP(tabId, "Page.captureScreenshot", { format: "png" });
// → Kullanıcının penceresine dokunmaz!
```

---

### 10. `nav_discover` / `nav_hover` — task Scope Hatası
**Dosya:** `agents/browser_ext_agent.py` → `_exec_step()`  
**Sorun:** `_exec_step` metodunda `task` değişkeni parametre olarak alınmıyordu, serbest değişken olarak referans ediliyordu → `NameError` veya yanlış değer.  
**Çözüm:** `task`, `emit`, `approval_callback` doğrudan parametre olarak eklendi:
```python
async def _exec_step(
    self,
    action, target, value, selector, step, tab_id, mouse,
    task: str = "", emit=None, approval_callback=None,  # ← ekle
) -> tuple[str, dict]:
```

---

### 11. `chrome.windows.create({ focused: false })` — Ayrı Pencere
**Sorun:** `chrome.tabs.create()` kullanıcının aktif penceresinde sekme açar → görev sırasında kullanıcının odağını bozar.  
**Çözüm:** Ayrı pencere:
```javascript
const win = await chrome.windows.create({
  url: "about:blank",
  focused: false,   // ← Kullanıcı penceresini çalmaz
  state: "normal",
  width: 1366, height: 800,
});
```

---

## 🏗️ Mimari Kararlar

### Extension ↔ Server İletişim Deseni
```
Kullanıcı UI (WS /ws)
    ↓
server.py _get_browser_agent()
    ↓ (extension bağlıysa)
BrowserExtAgent.send_command()
    ↓ (JSON over WS)
Chrome Extension (/ws/atlas-ext)
    ↓ (CDP)
Chrome Tab (background, kullanıcı görmez)
```

**asyncio.Future pattern:**
```python
_pending: dict[str, asyncio.Future] = {}

# Komut gönder
fut = asyncio.get_event_loop().create_future()
_pending[cmd_id] = fut
await ws.send_text(json.dumps({"id": cmd_id, "action": action, ...}))
result = await asyncio.wait_for(fut, timeout=timeout)

# Yanıt gelince (server.py'de)
def resolve_command(cmd_id, data):
    fut = _pending.get(cmd_id)
    if fut and not fut.done():
        fut.set_result(data)
```

---

### CAPTCHA Akışı
```
navigate() → get_text() → CAPTCHA sinyali var?
    ↓ Evet
emit(browser.captcha_needed)  → UI'da kırmızı banner göster
emit(browser.screenshot)      → Kullanıcı ekran görüntüsünü görür
approval_callback()            → UI'da "Tamamladım / Atla" butonları
    ↓ Kullanıcı "Tamamladım"
browser_approve → True → devam et
```

---

### Görev Sınıflandırması
`supervisor.classify_task(goal)` şu kategorileri döndürür:
- `"browser"` → BrowserExtAgent veya BrowserAgent
- `"property"` → PropertyAgent (emlak araması)
- `"car"` → CarAgent (araç araması)
- `"finance"` → FinanceAgent
- `"osint"` → OsintAgent
- `"music"` → MusicAgent
- `"code"` → Orchestrator (yazılım geliştirme)

---

## 📦 Kurulum Notları

### Chrome Extension İlk Kurulum
1. `chrome://extensions` → Geliştirici modu → Paketlenmemiş yükle
2. `F:\Projeler\Agent_Project\static\extension` klasörünü seç
3. Server çalışıyor olmalı: `python server.py`
4. Extension popup'ta "Sunucuya bağlı ✓" görmeli

### Extension Güncelleme (kod değişikliği sonrası)
```
chrome://extensions → Atlas → 🔄 Yeniden Yükle
```
→ Service worker yeniden başlar, yeni kod yüklenir.

### Gerekli Python Paketleri
```
fastapi, uvicorn, websockets, playwright, playwright-stealth
curl_cffi, beautifulsoup4, aiofiles, pypdf
anthropic, google-genai, ollama
```

---

## 🗺️ Dosya Haritası

```
Agent_Project/
├── server.py                    # FastAPI, WS /ws + /ws/atlas-ext
├── config.py                    # API keys, model seçimleri, port
├── orchestrator.py              # Supervisor + multi-agent iş akışı
├── agents/
│   ├── browser_ext_agent.py     # Chrome extension ile browser kontrolü
│   ├── browser_agent.py         # Playwright fallback (bot tespitine açık)
│   ├── property_agent.py        # Emlak araması (emlakjet.com)
│   ├── car_agent.py             # Araç araması (sahibinden)
│   ├── osint_agent.py           # Kişi/şirket araştırma
│   └── finance_agent.py         # Finansal analiz
├── tools/
│   ├── property_scraper.py      # emlakjet.com HTML scraper
│   └── maps_client.py           # Google Maps mesafe hesabı
└── static/
    ├── index.html               # Tek sayfa UI
    └── extension/
        ├── manifest.json        # MV3, permissions: alarms + debugger
        ├── background.js        # Service worker, CDP komutları, WS
        ├── content.js           # İçerik scripti
        └── popup.html/js        # Extension popup
```
