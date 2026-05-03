"""
Ücretsiz Mesafe Hesaplayıcı — OpenStreetMap + OSRM
=====================================================
API key gerektirmez, tamamen ücretsiz:
  • Nominatim  → adres/yer ismi → koordinat (OpenStreetMap geocoding)
  • OSRM       → iki nokta arası mesafe + süre (açık kaynak routing)
  • Sabit metro koordinatları → popüler duraklar için geocoding atlanır

Desteklenen modlar:
  "yürüyüş"   → OSRM foot   (en yaygın: metroya kaç dakika yürünür?)
  "araba"      → OSRM car
  "bisiklet"   → OSRM bike
  "transit"    → yürüyüş olarak işlenir (OSRM transit desteklemez ama
                  metro için yürüyüş mesafesi zaten daha anlamlı)
"""

from __future__ import annotations

import asyncio
import math
from typing import Optional

_HTTPX_OK = False
try:
    import httpx
    _HTTPX_OK = True
except ImportError:
    pass

# ─── Servis URL'leri ──────────────────────────────────────────────────────────

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_BASE     = "http://router.project-osrm.org/route/v1"

NOMINATIM_HEADERS = {
    "User-Agent": "MilaPropertySearch/1.0 (personal project)",
    "Accept-Language": "tr,en",
}

OSRM_PROFILE = {
    "yürüyüş": "foot",
    "walking":  "foot",
    "transit":  "foot",   # toplu taşıma → yürüyüş olarak yaklaşım
    "araba":    "car",
    "driving":  "car",
    "bisiklet": "bike",
    "bicycling":"bike",
}

# ─── İstanbul Metro / Ulaşım Koordinatları (sabit — geocoding atlanır) ───────
# (lat, lng)
ISTANBUL_POI_COORDS: dict[str, tuple[float, float]] = {
    # ── M1A/M1B ──────────────────────────────────────────────────────────────
    "Yenikapı Metro":          (41.0058, 28.9512),
    "Aksaray Metro":           (41.0130, 28.9498),
    "Bağcılar Metro":          (41.0390, 28.8512),
    "Kirazlı Metro":           (41.0437, 28.8286),
    "Atatürk Havalimanı Metro":(40.9749, 28.8124),
    # ── M2 ───────────────────────────────────────────────────────────────────
    "Şişhane Metro":           (41.0310, 28.9726),
    "Taksim Metro":            (41.0369, 28.9850),
    "Osmanbey Metro":          (41.0490, 28.9933),
    "Mecidiyeköy Metro":       (41.0665, 28.9946),
    "Gayrettepe Metro":        (41.0736, 28.9974),
    "Levent Metro":            (41.0823, 29.0109),
    "4. Levent Metro":         (41.0932, 29.0172),
    "Sanayi Metro":            (41.1047, 29.0158),
    "İTÜ-Ayazağa Metro":       (41.1059, 29.0188),
    "Atatürk Oto Sanayi Metro":(41.1168, 29.0154),
    "Darüşşafaka Metro":       (41.1258, 29.0154),
    "Hacıosman Metro":         (41.1336, 29.0176),
    # ── M3 ───────────────────────────────────────────────────────────────────
    "Başakşehir Metro":        (41.0930, 28.8054),
    "Olimpiyat Metro":         (41.0864, 28.7964),
    # ── M4 ───────────────────────────────────────────────────────────────────
    "Kadıköy Metro":           (40.9907, 29.0279),
    "Ayrılık Çeşmesi Metro":   (41.0034, 29.0354),
    "Acıbadem Metro":          (41.0087, 29.0449),
    "Ünalan Metro":            (41.0135, 29.0503),
    "Göztepe Metro":           (40.9882, 29.0686),
    "Yenisahra Metro":         (40.9797, 29.0783),
    "Kozyatağı Metro":         (40.9782, 29.0887),
    "Bostancı Metro":          (40.9638, 29.1019),
    "Küçükyalı Metro":         (40.9542, 29.1183),
    "Maltepe Metro":           (40.9333, 29.1293),
    "Huzurevi Metro":          (40.9230, 29.1313),
    "Gülsuyu Metro":           (40.9115, 29.1254),
    # ── M5 ───────────────────────────────────────────────────────────────────
    "Üsküdar Metro":           (41.0217, 29.0137),
    "Fıstıkağacı Metro":       (41.0175, 29.0441),
    "Bağlarbaşı Metro":        (41.0122, 29.0530),
    "Altunizade Metro":        (41.0267, 29.0590),
    "Kısıklı Metro":           (41.0288, 29.0703),
    "Çengelköy Metro":         (41.0454, 29.0690),
    "Kandilli Metro":          (41.0577, 29.0701),
    "Anadolu Hisarı Metro":    (41.0659, 29.0690),
    # ── Marmaray ─────────────────────────────────────────────────────────────
    "Marmaray Kazlıçeşme":     (40.9965, 28.9073),
    "Marmaray Yenikapı":       (41.0058, 28.9512),
    "Marmaray Sirkeci":        (41.0132, 28.9779),
    "Marmaray Üsküdar":        (41.0227, 29.0147),
    "Marmaray Ayrılık Çeşmesi":(41.0034, 29.0354),
    "Marmaray Söğütlüçeşme":   (40.9962, 29.0548),
    "Marmaray Bostancı":       (40.9638, 29.1019),
    "Marmaray Maltepe":        (40.9333, 29.1293),
    # ── İskele / Vapur ───────────────────────────────────────────────────────
    "Kadıköy İskelesi":        (40.9910, 29.0235),
    "Üsküdar İskelesi":        (41.0223, 29.0134),
    "Beşiktaş İskelesi":       (41.0426, 29.0048),
    "Kabataş İskelesi":        (41.0356, 28.9977),
    "Eminönü İskelesi":        (41.0164, 28.9726),
    "Karaköy İskelesi":        (41.0220, 28.9742),
    "Sarıyer İskelesi":        (41.1689, 29.0503),
    "Bostancı İskelesi":       (40.9638, 29.1019),
    # ── Genel ────────────────────────────────────────────────────────────────
    "Taksim Meydanı":          (41.0369, 28.9850),
    "Galata Kulesi":           (41.0256, 28.9742),
    "Sultanahmet":             (41.0054, 28.9768),
    "Boğaziçi Üniversitesi":   (41.0848, 29.0494),
    "İTÜ":                     (41.1058, 29.0188),
    "Sabiha Gökçen Havalimanı":(40.8982, 29.3092),
    "İstanbul Havalimanı":     (41.2762, 28.7519),
}


# ─── Geocoding ────────────────────────────────────────────────────────────────

async def geocode(place: str) -> Optional[tuple[float, float]]:
    """
    Yer adını koordinata çevir.
    Önce sabit listede ara, yoksa Nominatim'e sor.
    """
    # Sabit listede ara (büyük/küçük harf fark etmez)
    place_lower = place.lower().strip()
    for key, coords in ISTANBUL_POI_COORDS.items():
        if place_lower in key.lower() or key.lower() in place_lower:
            return coords

    # Nominatim'e sor
    if not _HTTPX_OK:
        return None
    try:
        async with httpx.AsyncClient(headers=NOMINATIM_HEADERS, timeout=8.0) as client:
            resp = await client.get(NOMINATIM_URL, params={
                "q":      place + ", İstanbul, Türkiye",
                "format": "json",
                "limit":  1,
            })
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


# ─── Düz çizgi mesafesi (fallback) ───────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """İki koordinat arası kuş uçuşu mesafe (km)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _format_distance(meters: float) -> str:
    if meters < 1000:
        return f"{int(meters)} m"
    return f"{meters/1000:.1f} km"


def _format_duration(seconds: float) -> str:
    minutes = int(seconds / 60)
    if minutes < 60:
        return f"~{minutes} dk"
    h, m = divmod(minutes, 60)
    return f"~{h}s {m}dk"


# ─── OSRM Routing ─────────────────────────────────────────────────────────────

async def route_osrm(
    origin_coords: tuple[float, float],
    dest_coords:   tuple[float, float],
    profile:       str = "foot",
) -> Optional[dict]:
    """
    OSRM ile iki nokta arası rota hesapla.
    Returns: {"distance_m": float, "duration_s": float} veya None
    """
    if not _HTTPX_OK:
        return None

    lat1, lon1 = origin_coords
    lat2, lon2 = dest_coords
    url = f"{OSRM_BASE}/{profile}/{lon1},{lat1};{lon2},{lat2}"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params={"overview": "false"})
            data = resp.json()
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                return {
                    "distance_m": route["distance"],
                    "duration_s": route["duration"],
                }
    except Exception:
        pass
    return None


# ─── Ana Fonksiyon ────────────────────────────────────────────────────────────

async def get_distance(
    origin: str,
    destination: str,
    mode: str = "yürüyüş",
) -> dict:
    """
    İki yer arası mesafe ve süre hesapla.

    Args:
        origin:      Kaynak (adres veya "lat,lng")
        destination: Hedef yer adı
        mode:        "yürüyüş" | "araba" | "bisiklet" | "transit"

    Returns:
        {"destination": str, "distance": str, "duration": str, "status": str}
    """
    result = {"destination": destination, "distance": "?", "duration": "?", "status": "ok"}

    # Koordinatları al
    if "," in origin and all(c.replace(".","").replace(",","").replace("-","").isdigit() for c in origin.split(",")[:2]):
        # Zaten koordinat formatı "lat,lng"
        parts = origin.split(",")
        try:
            origin_coords: Optional[tuple] = (float(parts[0]), float(parts[1]))
        except ValueError:
            origin_coords = None
    else:
        origin_coords = await geocode(origin)

    dest_coords = await geocode(destination)

    if not origin_coords:
        result["status"] = "origin_not_found"
        return result
    if not dest_coords:
        result["status"] = "dest_not_found"
        return result

    # OSRM profil seç
    osrm_profile = OSRM_PROFILE.get(mode.lower(), "foot")

    route = await route_osrm(origin_coords, dest_coords, osrm_profile)

    if route:
        result["distance"] = _format_distance(route["distance_m"])
        result["duration"] = _format_duration(route["duration_s"])
    else:
        # OSRM başarısız → kuş uçuşu mesafe hesapla
        km = haversine_km(*origin_coords, *dest_coords)
        result["distance"] = _format_distance(km * 1000)
        # Yürüyüş: ~5 km/s, araba: ~30 km/s (şehir içi)
        speed = 5.0 if osrm_profile == "foot" else 30.0
        minutes = (km / speed) * 60
        result["duration"] = _format_duration(minutes * 60)
        result["status"] = "approximate"

    return result


async def get_distances(
    origin:       str,
    destinations: list[str],
    mode:         str = "yürüyüş",
    api_key:      str = "",       # uyumluluk için, kullanılmıyor
) -> list[dict]:
    """
    Origin'den birden fazla hedefe mesafe hesapla.
    Nominatim rate limit'i için istekler arasında kısa bekleme var.
    """
    results = []
    for i, dest in enumerate(destinations):
        if i > 0:
            await asyncio.sleep(0.3)  # Nominatim rate limit: max ~3 req/s
        r = await get_distance(origin, dest, mode)
        results.append(r)
    return results


async def enrich_listing_with_distances(
    listing,
    pois:    list[str],
    api_key: str = "",    # artık kullanılmıyor ama uyumluluk için kaldı
    mode:    str = "yürüyüş",
) -> None:
    """Listing nesnesini mesafe bilgileriyle zenginleştir."""
    if not pois:
        return

    # Origin: koordinat varsa kullan, yoksa adres
    if listing.lat and listing.lng:
        origin = f"{listing.lat},{listing.lng}"
    elif listing.location:
        origin = listing.location + ", İstanbul"
    else:
        return

    distances = await get_distances(origin, pois, mode)

    for poi, dist_info in zip(pois, distances):
        listing.distances[poi] = {
            "distance": dist_info["distance"],
            "duration": dist_info["duration"],
        }


async def enrich_listings_batch(
    listings:       list,
    pois:           list[str],
    api_key:        str = "",
    mode:           str = "yürüyüş",
    max_concurrent: int = 3,
) -> None:
    """İlan listesini toplu mesafe bilgileriyle zenginleştir."""
    if not pois or not listings:
        return

    sem = asyncio.Semaphore(max_concurrent)

    async def _enrich_one(listing) -> None:
        async with sem:
            await enrich_listing_with_distances(listing, pois, api_key, mode)
            await asyncio.sleep(0.2)  # Nominatim rate limit

    await asyncio.gather(*[_enrich_one(l) for l in listings])


def parse_poi_request(query: str) -> list[str]:
    """
    Kullanıcı sorgusundan POI isteklerini çıkar.
    """
    q = query.lower()
    found = []

    # İstanbul metro hatları
    metro_lines = {
        "m1": "Yenikapı Metro", "m2": "Mecidiyeköy Metro",
        "m3": "Başakşehir Metro", "m4": "Kadıköy Metro",
        "m5": "Üsküdar Metro",
    }
    for line, poi in metro_lines.items():
        if line in q:
            found.append(poi)

    # Spesifik istasyon adları (ISTANBUL_POI_COORDS'tan)
    for poi_name in ISTANBUL_POI_COORDS:
        poi_lower = poi_name.lower()
        # Ana kelimeyi çıkar (örn: "Kadıköy Metro" → "kadıköy")
        main_word = poi_lower.split()[0]
        if len(main_word) > 4 and main_word in q:
            found.append(poi_name)

    # Genel kelime eşlemeleri
    if not found:
        keyword_map = {
            "metro":     "Kadıköy Metro",      # varsayılan: en popüler
            "metrobüs":  "Mecidiyeköy Metro",
            "iskele":    "Kadıköy İskelesi",
            "vapur":     "Kadıköy İskelesi",
            "marmaray":  "Marmaray Ayrılık Çeşmesi",
            "taksim":    "Taksim Meydanı",
            "havalimanı":"İstanbul Havalimanı",
            "sabiha":    "Sabiha Gökçen Havalimanı",
        }
        for kw, label in keyword_map.items():
            if kw in q:
                found.append(label)

    return list(dict.fromkeys(found))[:6]  # deduplicate, max 6
