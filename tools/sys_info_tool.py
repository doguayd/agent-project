"""
Sistem Bilgisi Aracı — Windows
================================
psutil ile CPU, RAM, disk, pil, ağ bilgisi.
macOS'a özgü komutlar kaldırıldı, Windows'a uyarlandı.

JARVIS (Alp Ünlü, @alppunlu) projesinden uyarlanmıştır.
"""

from __future__ import annotations

import datetime
import socket
import subprocess

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def sys_info(query: str = "all") -> str:
    query = (query or "all").lower().strip()
    results = []

    if query in ("battery", "pil", "all"):
        results.append(_battery())

    if query in ("cpu", "işlemci", "all"):
        results.append(_cpu())

    if query in ("ram", "bellek", "memory", "all"):
        results.append(_ram())

    if query in ("disk", "depolama", "all"):
        results.append(_disk())

    if query in ("time", "saat", "zaman", "all"):
        now = datetime.datetime.now()
        results.append(f"Saat: {now.strftime('%H:%M:%S')}")

    if query in ("date", "tarih", "all"):
        now = datetime.datetime.now()
        results.append(f"Tarih: {now.strftime('%d %B %Y, %A')}")

    if query in ("network", "ağ", "wifi", "ip", "all"):
        results.append(_network())

    if query in ("gpu", "ekran kartı", "vram"):
        results.append(_gpu())

    if not results:
        results.append(
            f"Bilinmeyen sorgu: '{query}'. "
            "Geçerli: battery | cpu | ram | disk | time | date | network | gpu | all"
        )

    return "\n".join(r for r in results if r)


def _battery() -> str:
    if not HAS_PSUTIL:
        return "Pil bilgisi için psutil gerekli."
    bat = psutil.sensors_battery()
    if not bat:
        return "Pil sensörü bulunamadı (masaüstü sistemi veya psutil desteklemiyor)."
    status = "Şarj oluyor 🔌" if bat.power_plugged else "Pilde 🔋"
    secs   = bat.secsleft
    if secs and secs > 0 and not bat.power_plugged:
        h, m = divmod(secs // 60, 60)
        time_str = f" — kalan ~{h}s {m}dk" if h else f" — kalan ~{m}dk"
    else:
        time_str = ""
    return f"Pil: %{bat.percent:.0f} — {status}{time_str}"


def _cpu() -> str:
    if not HAS_PSUTIL:
        return "CPU bilgisi için psutil gerekli."
    usage = psutil.cpu_percent(interval=0.5)
    count = psutil.cpu_count(logical=True)
    phys  = psutil.cpu_count(logical=False)
    freq  = psutil.cpu_freq()
    freq_str = f" @ {freq.current/1000:.1f} GHz" if freq else ""
    return f"CPU: %{usage:.1f} kullanım — {phys} fiziksel / {count} mantıksal çekirdek{freq_str}"


def _ram() -> str:
    if not HAS_PSUTIL:
        return "RAM bilgisi için psutil gerekli."
    vm    = psutil.virtual_memory()
    total = vm.total / (1024**3)
    used  = vm.used  / (1024**3)
    avail = vm.available / (1024**3)
    return f"RAM: {used:.1f}GB / {total:.1f}GB kullanımda (%{vm.percent:.0f}) — {avail:.1f}GB boş"


def _disk() -> str:
    if not HAS_PSUTIL:
        return "Disk bilgisi için psutil gerekli."
    parts = []
    for part in psutil.disk_partitions():
        if "cdrom" in part.opts or part.fstype == "":
            continue
        try:
            du = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        total = du.total / (1024**3)
        used  = du.used  / (1024**3)
        free  = du.free  / (1024**3)
        parts.append(
            f"{part.device} ({part.mountpoint}): "
            f"{used:.1f}GB / {total:.1f}GB — {free:.1f}GB boş (%{du.percent:.0f})"
        )
    return "\n".join(parts) if parts else "Disk bilgisi alınamadı."


def _network() -> str:
    results = []
    # Hostname + local IP
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        results.append(f"Hostname: {hostname} — IP: {local_ip}")
    except Exception:
        pass

    # Network interfaces (psutil)
    if HAS_PSUTIL:
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            for iface, stat in stats.items():
                if not stat.isup or iface == "lo":
                    continue
                ips = [a.address for a in addrs.get(iface, [])
                       if a.family == socket.AF_INET]
                if ips:
                    results.append(f"  {iface}: {', '.join(ips)} ({'aktif' if stat.isup else 'inaktif'})")
        except Exception:
            pass

    # Windows: WiFi SSID
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
            encoding="utf-8", errors="replace"
        )
        for line in out.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[-1].strip()
                if ssid:
                    results.append(f"  WiFi SSID: {ssid}")
                    break
    except Exception:
        pass

    return "\n".join(results) if results else "Ağ bilgisi alınamadı."


def _gpu() -> str:
    # nvidia-smi varsa kullan
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5, stderr=subprocess.DEVNULL
        )
        results = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                name, mem_used, mem_total, util, temp = parts[:5]
                results.append(
                    f"GPU: {name} — VRAM {mem_used}MB/{mem_total}MB "
                    f"— Kullanım %{util} — {temp}°C"
                )
        return "\n".join(results) if results else "GPU bilgisi alınamadı."
    except FileNotFoundError:
        return "nvidia-smi bulunamadı (GPU bilgisi için NVIDIA sürücüsü gerekli)."
    except Exception:
        return "GPU bilgisi alınamadı."
