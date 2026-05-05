/**
 * Atlas Content Script
 * ====================
 * Sayfa içinde çalışır — ek DOM erişimi gerektiğinde background.js
 * bu script aracılığıyla veri alabilir.
 */

// Background script'e sayfa hazır sinyali gönder
chrome.runtime.sendMessage({ type: "page.ready", url: window.location.href });

// İleride ek içerik script özellikler buraya eklenebilir
