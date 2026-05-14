"""
Emlak İlan Scraper — emlakjet.com
====================================
emlakjet.com üzerinden Türkiye genelinde kiralık/satılık ilan araması.
  • curl_cffi ile Chrome imzası — bot koruması bypass
  • BeautifulSoup ile HTML parse
  • Sahibinden.com linkleri de emlakjet üzerinden erişilebilir

Desteklenen kategoriler: kiralik-konut, satilik-konut, kiralik-isyeri, satilik-isyeri
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode, quote_plus

_CURL_OK = False
try:
    from curl_cffi.requests import AsyncSession
    _CURL_OK = True
except ImportError:
    pass

_BS4_OK = False
try:
    from bs4 import BeautifulSoup
    _BS4_OK = True
except ImportError:
    pass

# ─── Sabitler ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.emlakjet.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Kategori slug → emlakjet URL path
CATEGORY_MAP = {
    # Kiralık konut
    "kiralik daire":   "kiralik-konut",
    "kiralık daire":   "kiralik-konut",
    "kiralik ev":      "kiralik-konut",
    "kiralık ev":      "kiralik-konut",
    "kiralik konut":   "kiralik-konut",
    "kiralık konut":   "kiralik-konut",
    "kiralik villa":   "kiralik-konut",
    "kiralık villa":   "kiralik-konut",
    # Satılık konut
    "satilik daire":   "satilik-konut",
    "satılık daire":   "satilik-konut",
    "satilik ev":      "satilik-konut",
    "satılık ev":      "satilik-konut",
    "satilik konut":   "satilik-konut",
    "satılık konut":   "satilik-konut",
    "satilik villa":   "satilik-konut",
    "satılık villa":   "satilik-konut",
    # Kiralık iş yeri
    "kiralik ofis":    "kiralik-isyeri",
    "kiralık ofis":    "kiralik-isyeri",
    "kiralik isyeri":  "kiralik-isyeri",
    "kiralık işyeri":  "kiralik-isyeri",
    # Satılık iş yeri
    "satilik ofis":    "satilik-isyeri",
    "satılık ofis":    "satilik-isyeri",
}

# İl slug'ları (küçük harf, Türkçe karakter düzeltmeli)
CITY_SLUGS = {
    "istanbul": "istanbul", "ankara": "ankara", "izmir": "izmir",
    "bursa": "bursa", "antalya": "antalya", "adana": "adana",
    "konya": "konya", "gaziantep": "gaziantep", "mersin": "mersin",
    "kocaeli": "kocaeli", "eskisehir": "eskisehir", "eskişehir": "eskisehir",
    "kayseri": "kayseri", "samsun": "samsun", "trabzon": "trabzon",
    "manisa": "manisa", "diyarbakir": "diyarbakir", "diyarbakır": "diyarbakir",
}

# İlçe slug'ları (İstanbul + diğer büyük şehirler)
DISTRICT_SLUGS = {
    "kadıköy":        "kadikoy",   "kadikoy":       "kadikoy",
    "beşiktaş":       "besiktas",  "besiktas":      "besiktas",
    "üsküdar":        "uskudar",   "uskudar":       "uskudar",
    "şişli":          "sisli",     "sisli":         "sisli",
    "beyoğlu":        "beyoglu",   "beyoglu":       "beyoglu",
    "maltepe":        "maltepe",
    "ümraniye":       "umraniye",  "umraniye":      "umraniye",
    "ataşehir":       "atasehir",  "atasehir":      "atasehir",
    "pendik":         "pendik",
    "sultanbeyli":    "sultanbeyli",
    "beykoz":         "beykoz",
    "sancaktepe":     "sancaktepe",
    "sultangazi":     "sultangazi",
    "arnavutköy":     "arnavutkoy", "arnavutkoy":   "arnavutkoy",
    "esenyurt":       "esenyurt",
    "başakşehir":     "basaksehir", "basaksehir":   "basaksehir",
    "bakırköy":       "bakirkoy",  "bakirkoy":      "bakirkoy",
    "kartal":         "kartal",
    "sarıyer":        "sariyer",   "sariyer":       "sariyer",
    "kağıthane":      "kagithane", "kagithane":     "kagithane",
    "fatih":          "fatih",
    "bağcılar":       "bagcilar",  "bagcilar":      "bagcilar",
    "zeytinburnu":    "zeytinburnu",
    "esenler":        "esenler",
    "gaziosmanpaşa":  "gaziosmanpasa",
    "tuzla":          "tuzla",
    "çekmeköy":       "cekmekoy",  "cekmekoy":      "cekmekoy",
    "sultanbeyli":    "sultanbeyli",
    "silivri":        "silivri",
    "büyükçekmece":   "buyukcekmece",
    "küçükçekmece":   "kucukcekmece",
    "bayrampaşa":     "bayrampasa",
    "eyüpsultan":     "eyupsultan", "eyüp":         "eyup",
    "avcılar":        "avcilar",   "avcilar":       "avcilar",
    "bahçelievler":   "bahcelievler",
    "güngören":       "gungoren",
    "sultanahmet":    "fatih",
    # Ankara
    "çankaya":        "cankaya",   "cankaya":       "cankaya",
    "keçiören":       "kecioren",  "kecioren":      "kecioren",
    "mamak":          "mamak",
    "yenimahalle":    "yenimahalle",
    "etimesgut":      "etimesgut",
    # İzmir
    "konak":          "konak",
    "karşıyaka":      "karsiyaka",
    "bornova":        "bornova",
    "buca":           "buca",
}

# Oda sayısı → emlakjet room_count param
ROOM_PARAM = {
    "1+0": "1%2B0", "1+1": "1%2B1", "2+1": "2%2B1",
    "3+1": "3%2B1", "4+1": "4%2B1", "5+1": "5%2B1",
    "studio": "1%2B0",
}


# ─── Veri Modeli ──────────────────────────────────────────────────────────────

@dataclass
class Listing:
    title:       str
    price:       str
    location:    str
    area:        str
    rooms:       str
    floor:       str
    url:         str
    image_url:   str             = ""
    listing_id:  str             = ""
    description: str             = ""
    lat:         Optional[float] = None
    lng:         Optional[float] = None
    distances:   dict            = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title":       self.title,
            "price":       self.price,
            "location":    self.location,
            "area":        self.area,
            "rooms":       self.rooms,
            "floor":       self.floor,
            "url":         self.url,
            "image_url":   self.image_url,
            "listing_id":  self.listing_id,
            "description": self.description,
            "lat":         self.lat,
            "lng":         self.lng,
            "distances":   self.distances,
        }


# ─── Sorgu Ayrıştırıcı ────────────────────────────────────────────────────────

def _parse_query(query: str) -> tuple[str, str, str, dict]:
    """
    Doğal dil sorgusunu ayrıştır.
    Returns: (category_path, city_slug, district_slug, extra_params)
    """
    q = query.lower().strip()

    # Kategori — önce satılık/kiralık ana sözcüğü tespit et
    category = "kiralik-konut"   # varsayılan
    is_satilik = any(kw in q for kw in ("satılık", "satilik", "satmak", "satışa"))
    is_kiralik = any(kw in q for kw in ("kiralık", "kiralik", "kira", "kiralamak"))
    is_isyeri  = any(kw in q for kw in ("ofis", "iş yeri", "işyeri", "isyeri", "dükkan", "depo", "ticari"))

    if is_satilik:
        category = "satilik-isyeri" if is_isyeri else "satilik-konut"
    elif is_kiralik:
        category = "kiralik-isyeri" if is_isyeri else "kiralik-konut"
    else:
        # Eski anahtar kelime eşleştirmesine geri dön
        for kw, cat in CATEGORY_MAP.items():
            if kw in q:
                category = cat
                break

    # Şehir
    city_slug = "istanbul"   # varsayılan
    for city, slug in CITY_SLUGS.items():
        if city in q:
            city_slug = slug
            break

    # İlçe
    district_slug = ""
    for district, slug in DISTRICT_SLUGS.items():
        if district in q:
            district_slug = slug
            break

    # Extra params
    params: dict = {}

    # Oda sayısı: 2+1, 3+1 vb.
    room_m = re.search(r"(\d+)\+(\d+)", q)
    if room_m:
        rooms_str = f"{room_m.group(1)}+{room_m.group(2)}"
        params["room_count"] = rooms_str

    # Fiyat aralığı
    price_m = re.search(r"(\d[\d.]*)\s*[-–]\s*(\d[\d.]*)", q)
    if price_m:
        p1 = int(price_m.group(1).replace(".", ""))
        p2 = int(price_m.group(2).replace(".", ""))
        params["price_min"] = min(p1, p2)
        params["price_max"] = max(p1, p2)
    else:
        max_m = re.search(r"(?:max|en fazla|en çok|maksimum|kadar)\s*(\d[\d.]*)", q)
        if max_m:
            params["price_max"] = int(max_m.group(1).replace(".", ""))
        min_m = re.search(r"(?:min|en az|minimum|üzeri|fazla)\s*(\d[\d.]*)", q)
        if min_m:
            params["price_min"] = int(min_m.group(1).replace(".", ""))

    # Alan (m²)
    area_m = re.search(r"(\d+)\s*(?:m²|m2|metrekare)", q)
    if area_m:
        params["area_min"] = int(area_m.group(1))

    return category, city_slug, district_slug, params


def _build_url(category: str, city: str, district: str, params: dict) -> str:
    """emlakjet.com arama URL'si oluştur."""
    # Path: /kiralik-konut/istanbul-kadikoy/
    if district:
        path = f"/{category}/{city}-{district}/"
    else:
        path = f"/{category}/{city}/"

    url = BASE_URL + path

    # Query string
    qs_parts = []
    if "room_count" in params:
        # room_count needs to be encoded as "2%2B1" (+ → %2B)
        rooms = params["room_count"].replace("+", "%2B")
        qs_parts.append(f"room_count={rooms}")
    if "price_min" in params:
        qs_parts.append(f"price_min={params['price_min']}")
    if "price_max" in params:
        qs_parts.append(f"price_max={params['price_max']}")
    if "area_min" in params:
        qs_parts.append(f"area_min={params['area_min']}")

    if qs_parts:
        url += "?" + "&".join(qs_parts)

    return url


# ─── HTML Parser ──────────────────────────────────────────────────────────────

def _parse_item(item) -> Optional[Listing]:
    """emlakjet listing div'inden Listing çıkar."""
    try:
        listing_id = item.get("data-id", "")

        # URL
        link_el = item.find("a")
        href = link_el.get("href", "") if link_el else ""
        url = BASE_URL + href if href.startswith("/") else href

        # Text content with pipe separator for parsing
        text = item.get_text(separator="|", strip=True)

        # Title: genellikle ikinci segment (ilk segment badge olabilir)
        segments = [s.strip() for s in text.split("|") if s.strip()]
        title = ""
        for seg in segments:
            # İlk uzun segment başlık
            if len(seg) > 10 and not re.match(r"^[\d.,\s]+$", seg) and "TL" not in seg:
                title = seg
                break
        if not title and segments:
            title = segments[0]

        # Fiyat: "52.500" + "TL" şeklinde ayrı segmentlerde gelebilir
        price = ""
        for i, seg in enumerate(segments):
            if seg == "TL" and i > 0:
                price = segments[i - 1].strip() + " TL"
                break
            m = re.search(r"([\d]{2,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*TL", seg)
            if m:
                price = m.group(0)
                break

        # Oda sayısı
        rooms = ""
        rooms_m = re.search(r"\b(\d\+\d)\b", text)
        if rooms_m:
            rooms = rooms_m.group(1)

        # Alan
        area = ""
        area_m = re.search(r"(\d{2,4})\s*m", text)
        if area_m:
            area = area_m.group(1) + " m²"

        # Kat
        floor = ""
        floor_m = re.search(r"(\d+)\.\s*[Kk]at", text)
        if floor_m:
            floor = floor_m.group(0)
        elif "Bodrum" in text:
            floor = "Bodrum Kat"
        elif "Giriş" in text:
            floor = "Giriş Katı"

        # Konum: segment "İlçe - Mahalle" formatında
        location = ""
        loc_m = re.search(r"([A-ZÇĞİÖŞÜa-zçğışöşü][\w\s]+)\s*[-–]\s*([A-ZÇĞİÖŞÜ][\w\s]+(?:Mahallesi|Mh\.|Semti))", text)
        if loc_m:
            location = loc_m.group(0)
        else:
            # 2. ve 3. segment arasında konum var
            for seg in segments[1:4]:
                if any(x in seg for x in ["Mahallesi", " - ", "Mh.", "İlçe"]):
                    location = seg
                    break

        # Görsel
        img_el = item.find("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        if not title and not listing_id:
            return None

        return Listing(
            title=title[:120],
            price=price,
            location=location,
            area=area,
            rooms=rooms,
            floor=floor,
            url=url,
            image_url=image_url,
            listing_id=listing_id,
            description="",
        )
    except Exception:
        return None


# ─── Ana Arama Fonksiyonu ─────────────────────────────────────────────────────

async def search_listings(
    query: str,
    max_results: int = 20,
    timeout_s: float = 15.0,
) -> tuple[list[Listing], str]:
    """
    emlakjet.com'da ilan arar.
    Returns: (listings, search_url)
    """
    if not _CURL_OK or not _BS4_OK:
        return [], ""

    category, city, district, params = _parse_query(query)
    url = _build_url(category, city, district, params)

    try:
        async with AsyncSession() as session:
            resp = await session.get(url, impersonate="chrome124", timeout=timeout_s)
            if resp.status_code != 200:
                return [], url

            soup     = BeautifulSoup(resp.text, "html.parser")
            items    = soup.find_all(attrs={"data-id": True})
            listings = []

            for item in items[:max_results]:
                listing = _parse_item(item)
                if listing:
                    listings.append(listing)

            # Fallback: geniş arama (fiyat kısıtı olmadan)
            if not listings and (params.get("price_min") or params.get("price_max")):
                broad_params = {k: v for k, v in params.items()
                                if k not in ("price_min", "price_max")}
                broad_url = _build_url(category, city, district, broad_params)
                resp2 = await session.get(broad_url, impersonate="chrome124", timeout=timeout_s)
                if resp2.status_code == 200:
                    soup2 = BeautifulSoup(resp2.text, "html.parser")
                    items2 = soup2.find_all(attrs={"data-id": True})
                    for item in items2[:max_results]:
                        listing = _parse_item(item)
                        if listing:
                            listings.append(listing)
                    url = broad_url

            return listings, url

    except Exception:
        return [], url


# ─── Detay Sayfası ───────────────────────────────────────────────────────────

async def fetch_listing_detail(listing_url: str, timeout_s: float = 10.0) -> dict:
    """
    İlan detay sayfasını çek.
    Returns: {"description": ..., "lat": ..., "lng": ...}
    """
    if not _CURL_OK or not _BS4_OK:
        return {}

    # emlakjet URL ise düzelt
    if listing_url.startswith("/"):
        listing_url = BASE_URL + listing_url

    try:
        async with AsyncSession() as session:
            resp = await session.get(listing_url, impersonate="chrome124", timeout=timeout_s)
            if resp.status_code != 200:
                return {}
            text = resp.text
    except Exception:
        return {}

    result: dict = {}
    soup = BeautifulSoup(text, "html.parser")

    # Açıklama
    desc_el = soup.find(attrs={"data-testid": "description"}) or \
              soup.find(class_=re.compile(r"description|aciklama", re.I))
    if desc_el:
        result["description"] = desc_el.get_text(strip=True)[:800]

    # Koordinatlar
    lat_m = re.search(r'"latitude"\s*:\s*"?([\d.]+)"?', text)
    lng_m = re.search(r'"longitude"\s*:\s*"?([\d.]+)"?', text)
    if lat_m and lng_m:
        try:
            result["lat"] = float(lat_m.group(1))
            result["lng"] = float(lng_m.group(1))
        except ValueError:
            pass

    return result
