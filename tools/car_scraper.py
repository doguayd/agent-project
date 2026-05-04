"""
Araç Arama — arabam.com Scraper
=================================
Turbo ajanı için arabam.com'dan ikinci el araç ilanlarını çeker.
curl_cffi ile Chrome TLS parmak izi taklidi yaparak bot korumasını geçer.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urlencode, quote

try:
    from curl_cffi.requests import AsyncSession
    _CURL_OK = True
except ImportError:
    _CURL_OK = False
    import httpx

from bs4 import BeautifulSoup

# ─── Veri Modeli ─────────────────────────────────────────────────────────────

@dataclass
class CarListing:
    title:     str = ""
    price:     str = ""
    year:      str = ""
    km:        str = ""
    location:  str = ""
    fuel:      str = ""
    gear:      str = ""
    url:       str = ""
    image_url: str = ""
    distances: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Kategori / Marka Eşlemeleri ─────────────────────────────────────────────

CATEGORY_MAP = {
    "otomobil": "otomobil",
    "araba":    "otomobil",
    "suv":      "suv-arazi",
    "arazi":    "suv-arazi",
    "pickup":   "pickup",
    "ticari":   "hafif-ticari",
    "van":      "hafif-ticari",
    "minivan":  "minivan",
    "sedan":    "otomobil",
    "hatchback":"otomobil",
    "coupe":    "otomobil",
    "cabrio":   "otomobil",
    "motosiklet":"motosiklet",
    "motor":    "motosiklet",
}

BRAND_MAP = {
    "bmw": "bmw", "mercedes": "mercedes-benz", "audi": "audi",
    "toyota": "toyota", "honda": "honda", "volkswagen": "volkswagen",
    "vw": "volkswagen", "ford": "ford", "opel": "opel",
    "renault": "renault", "peugeot": "peugeot", "fiat": "fiat",
    "hyundai": "hyundai", "kia": "kia", "nissan": "nissan",
    "volvo": "volvo", "skoda": "skoda", "seat": "seat",
    "dacia": "dacia", "citroen": "citroen", "mazda": "mazda",
    "mitsubishi": "mitsubishi", "subaru": "subaru", "suzuki": "suzuki",
    "tesla": "tesla", "porsche": "porsche", "land rover": "land-rover",
    "jeep": "jeep", "chevrolet": "chevrolet", "alfa romeo": "alfa-romeo",
    "mini": "mini", "lexus": "lexus", "infiniti": "infiniti",
    "togg": "togg", "chery": "chery", "byd": "byd",
}

FUEL_MAP = {
    "benzin": "gasoline", "dizel": "diesel", "hybrid": "hybrid",
    "hibrit": "hybrid", "elektrik": "electric", "lpg": "lpg",
    "elektrikli": "electric",
}

GEAR_MAP = {
    "otomatik": "automatic", "manuel": "manual", "yarı otomatik": "semi-automatic",
    "düz vites": "manual",
}


# ─── Sorgu Parser ─────────────────────────────────────────────────────────────

def _parse_car_query(query: str) -> dict:
    """
    Doğal dil araç sorgusunu parametrelere dönüştür.
    Örn: "2020 BMW 3 serisi dizel otomatik 500000 altı"
    """
    q = query.lower()

    # Kategori
    category = "otomobil"
    for kw, cat in CATEGORY_MAP.items():
        if kw in q:
            category = cat
            break

    # Marka
    brand_slug = None
    for kw, slug in BRAND_MAP.items():
        if kw in q:
            brand_slug = slug
            break

    # Yıl aralığı
    years = re.findall(r"\b(19|20)\d{2}\b", q)
    year_min = year_max = None
    if len(years) == 1:
        yr = int(years[0])
        if any(w in q for w in ["üstü", "sonrası", "ve sonrası", "+"]):
            year_min = yr
        elif any(w in q for w in ["altı", "öncesi", "ve öncesi"]):
            year_max = yr
        else:
            year_min = yr
    elif len(years) >= 2:
        year_min, year_max = int(min(years)), int(max(years))

    # Fiyat aralığı
    prices = re.findall(r"[\d.,]+(?:\s*(?:bin|k|milyon|m|tl))?", q)
    price_min = price_max = None
    raw_numbers = []
    for p in re.finditer(r"(\d[\d.]*)\s*(bin|k|milyon|m)?", q):
        num = float(p.group(1).replace(".", "").replace(",", "."))
        mult = p.group(2) or ""
        if "bin" in mult or mult == "k":
            num *= 1000
        elif "milyon" in mult or mult == "m":
            num *= 1_000_000
        if num >= 10_000:  # Fiyat olarak kabul et
            raw_numbers.append(int(num))

    if len(raw_numbers) == 1:
        n = raw_numbers[0]
        if any(w in q for w in ["altı", "altında", "max", "maksimum"]):
            price_max = n
        elif any(w in q for w in ["üstü", "üzerinde", "min", "minimum"]):
            price_min = n
        else:
            price_max = n
    elif len(raw_numbers) >= 2:
        price_min, price_max = min(raw_numbers[:2]), max(raw_numbers[:2])

    # km
    km_max = None
    km_m = re.search(r"(\d+)\s*(?:bin)?\s*km", q)
    if km_m:
        km_val = int(km_m.group(1))
        if km_m.group(0).count("bin") or km_val < 1000:
            km_val *= 1000
        km_max = km_val

    # Yakıt & Vites
    fuel = next((v for k, v in FUEL_MAP.items() if k in q), None)
    gear = next((v for k, v in GEAR_MAP.items() if k in q), None)

    return {
        "category":  category,
        "brand":     brand_slug,
        "year_min":  year_min,
        "year_max":  year_max,
        "price_min": price_min,
        "price_max": price_max,
        "km_max":    km_max,
        "fuel":      fuel,
        "gear":      gear,
    }


def _build_arabam_url(params: dict) -> str:
    """arabam.com arama URL'si oluştur."""
    category = params.get("category", "otomobil")
    brand    = params.get("brand")

    if brand:
        base = f"https://www.arabam.com/ikinci-el/{category}/{brand}"
    else:
        base = f"https://www.arabam.com/ikinci-el/{category}"

    qs: dict[str, str] = {"take": "20", "skip": "0"}

    if params.get("year_min"):  qs["year_start"] = str(params["year_min"])
    if params.get("year_max"):  qs["year_end"]   = str(params["year_max"])
    if params.get("price_min"): qs["minPrice"]   = str(params["price_min"])
    if params.get("price_max"): qs["maxPrice"]   = str(params["price_max"])
    if params.get("km_max"):    qs["km_end"]     = str(params["km_max"])
    if params.get("fuel"):      qs["fuelType"]   = params["fuel"]
    if params.get("gear"):      qs["gearType"]   = params["gear"]

    return base + "?" + urlencode(qs)


# ─── HTML Parser ─────────────────────────────────────────────────────────────

def _parse_listing(item) -> Optional[CarListing]:
    """Bir ilan kartını parse et."""
    try:
        # Başlık
        title_el = item.select_one("a.listing-text-new, h3.listing-title, .listing-text")
        title = title_el.get_text(strip=True) if title_el else ""

        # URL
        link_el = item.select_one("a[href*='/ikinci-el/']")
        url = ""
        if link_el and link_el.get("href"):
            href = link_el["href"]
            url = href if href.startswith("http") else "https://www.arabam.com" + href

        # Fiyat
        price_el = item.select_one(".listing-price, [class*='price']")
        price = price_el.get_text(strip=True) if price_el else ""

        # Yıl, km, şehir vs. — genellikle bir liste içinde
        attrs = item.select("ul.listing-info li, .listing-specs li, [class*='spec']")
        attr_texts = [a.get_text(strip=True) for a in attrs]

        year = km = location = fuel = gear = ""
        for t in attr_texts:
            if re.match(r"^(19|20)\d{2}$", t):
                year = t
            elif "km" in t.lower():
                km = t
            elif any(c in t for c in ["İl", "il", "İstanbul", "Ankara", "İzmir"]):
                location = t
            elif t in ["Benzin", "Dizel", "Hibrit", "Elektrik", "LPG"]:
                fuel = t
            elif t in ["Otomatik", "Manuel", "Yarı Otomatik", "CVT"]:
                gear = t

        # Konum ayrı elemanda da olabilir
        if not location:
            loc_el = item.select_one(".listing-location, [class*='location']")
            if loc_el:
                location = loc_el.get_text(strip=True)

        # Resim
        img_el = item.select_one("img[src]")
        image_url = img_el.get("src", "") if img_el else ""
        if image_url.startswith("//"):
            image_url = "https:" + image_url

        if not title and not price:
            return None

        return CarListing(
            title=title, price=price, year=year, km=km,
            location=location, fuel=fuel, gear=gear,
            url=url, image_url=image_url,
        )
    except Exception:
        return None


# ─── Ana Arama Fonksiyonu ─────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer":         "https://www.arabam.com/",
}


async def search_cars(
    query:       str,
    max_results: int = 15,
    timeout_s:   float = 20.0,
) -> tuple[list[CarListing], str]:
    """
    arabam.com'da araç ara.
    Returns: (listings, search_url)
    """
    params     = _parse_car_query(query)
    search_url = _build_arabam_url(params)

    async def _fetch(url: str) -> str:
        if _CURL_OK:
            async with AsyncSession() as s:
                r = await s.get(url, headers=_HEADERS, impersonate="chrome124", timeout=timeout_s)
                return r.text
        else:
            async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as c:
                r = await c.get(url, timeout=timeout_s)
                return r.text

    try:
        html = await asyncio.wait_for(_fetch(search_url), timeout=timeout_s)
    except Exception as e:
        return [], search_url

    soup = BeautifulSoup(html, "html.parser")

    # arabam.com kart seçicileri
    selectors = [
        "tr.listing-list-item",
        "div.listing-item",
        "article.listing-card",
        "[class*='listing-item']",
        "[data-id]",
    ]

    items = []
    for sel in selectors:
        items = soup.select(sel)
        if items:
            break

    # Fallback: tüm <tr> içinde link var mı
    if not items:
        items = [
            tr for tr in soup.select("tr")
            if tr.select_one("a[href*='/ikinci-el/']")
        ]

    listings: list[CarListing] = []
    for item in items[:max_results]:
        listing = _parse_listing(item)
        if listing:
            listings.append(listing)

    # Fallback: fiyat bulunamadıysa fiyat filtresini kaldır
    if not listings and (params.get("price_min") or params.get("price_max")):
        params2 = {k: v for k, v in params.items()
                   if k not in ("price_min", "price_max")}
        fallback_url = _build_arabam_url(params2)
        try:
            html2 = await asyncio.wait_for(_fetch(fallback_url), timeout=timeout_s)
            soup2 = BeautifulSoup(html2, "html.parser")
            for sel in selectors:
                items2 = soup2.select(sel)
                if items2:
                    for item in items2[:max_results]:
                        lst = _parse_listing(item)
                        if lst:
                            listings.append(lst)
                    break
            if listings:
                search_url = fallback_url
        except Exception:
            pass

    return listings, search_url
