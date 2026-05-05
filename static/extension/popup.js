const dot    = document.getElementById("dot");
const status = document.getElementById("status");
const openBtn = document.getElementById("openBtn");

// Background'dan bağlantı durumunu al
chrome.runtime.sendMessage({ type: "get.status" }, (resp) => {
  if (resp && resp.connected) {
    dot.classList.add("connected");
    status.textContent = "Sunucuya bağlı ✓";
  } else {
    status.textContent = "Sunucuya bağlanılamadı";
  }
});

openBtn.addEventListener("click", () => {
  chrome.tabs.create({ url: "http://localhost:8000" });
});
