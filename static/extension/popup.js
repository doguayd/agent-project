const dot    = document.getElementById("dot");
const status = document.getElementById("status");
const openBtn = document.getElementById("openBtn");

// WS durumu → okunabilir metin
const WS_LABELS = {
  0: "Bağlanıyor...",
  1: "Sunucuya bağlı ✓",
  2: "Bağlantı kapatılıyor...",
  3: "Sunucu bağlantısı yok ✗",
 "-1": "Service worker uyandırılıyor...",
};

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "get.status" }, (resp) => {
    // "Could not establish connection" — SW henüz uyanmamış
    if (chrome.runtime.lastError || !resp) {
      dot.classList.remove("connected");
      status.textContent = "Service worker başlatılıyor...";
      return;
    }
    if (resp.connected) {
      dot.classList.add("connected");
      status.textContent = "Sunucuya bağlı ✓";
    } else {
      dot.classList.remove("connected");
      const label = WS_LABELS[resp.wsState] || WS_LABELS["-1"];
      status.textContent = label;
    }
  });
}

// İlk kontrol + 2s'de bir otomatik yenile (popup açık olduğu sürece)
refreshStatus();
setInterval(refreshStatus, 2000);

openBtn.addEventListener("click", () => {
  chrome.tabs.create({ url: "http://localhost:8000" });
});
