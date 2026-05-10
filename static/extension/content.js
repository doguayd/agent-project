/**
 * Atlas Content Script
 * ====================
 * Sayfa içinde çalışır — ek DOM erişimi gerektiğinde background.js
 * bu script aracılığıyla veri alabilir.
 */

// Background script'e sayfa hazır sinyali gönder (hata yoksay — SW henüz uyanık olmayabilir)
try {
  chrome.runtime.sendMessage({ type: "page.ready", url: window.location.href }, () => {
    void chrome.runtime.lastError; // "Receiving end does not exist" hatasını sustur
  });
} catch (_) {}

// İleride ek içerik script özellikler buraya eklenebilir
