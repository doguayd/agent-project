"""
Hava Durumu Aracı
==================
wttr.in üzerinden şehir bazlı hava durumu özeti.
Harici bağımlılık yok — sadece requests.

JARVIS (Alp Ünlü, @alppunlu) projesinden uyarlanmıştır.
"""

from __future__ import annotations

import os

import requests


DEFAULT_LOCATION = os.environ.get("ATLAS_WEATHER_LOCATION", "Istanbul")


def get_weather_summary(location: str | None = None) -> str:
    target = (location or DEFAULT_LOCATION).strip()
    try:
        response = requests.get(
            f"https://wttr.in/{target}",
            params={"format": "j1"},
            timeout=10,
            headers={"User-Agent": "Atlas/1.0"},
        )
        response.raise_for_status()
        payload  = response.json()
        current  = (payload.get("current_condition") or [{}])[0]
        temp_c      = current.get("temp_C")
        feels_like  = current.get("FeelsLikeC")
        weather_desc = ((current.get("weatherDesc") or [{}])[0]).get("value", "")
        humidity    = current.get("humidity")
        wind_kmph   = current.get("windspeedKmph")

        parts = []
        if temp_c:
            parts.append(f"{temp_c}°C")
        if weather_desc:
            parts.append(weather_desc)
        if feels_like and feels_like != temp_c:
            parts.append(f"hissedilen {feels_like}°C")
        if humidity:
            parts.append(f"nem %{humidity}")
        if wind_kmph:
            parts.append(f"rüzgar {wind_kmph} km/s")

        if not parts:
            return "Hava durumu bilgisi alınamadı."

        # 3 günlük tahmin (varsa)
        forecast_parts = []
        for day in (payload.get("weather") or [])[:3]:
            date = day.get("date", "")
            max_c = day.get("maxtempC", "")
            min_c = day.get("mintempC", "")
            desc  = ((day.get("hourly") or [{}])[4].get("weatherDesc") or [{}])[0].get("value", "")
            if date and max_c and min_c:
                forecast_parts.append(f"{date}: {min_c}-{max_c}°C {desc}".strip())

        summary = f"{target} hava durumu: " + ", ".join(parts) + "."
        if forecast_parts:
            summary += "\n3 günlük tahmin: " + " | ".join(forecast_parts)
        return summary

    except Exception:
        return f"{target} için hava durumu bilgisi şu an alınamadı."


async def get_weather_async(location: str | None = None) -> dict:
    """Async wrapper — server.py event handler'larından çağrılır."""
    import asyncio
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: get_weather_summary(location))
    return {
        "success": "alınamadı" not in result,
        "summary": result,
        "location": location or DEFAULT_LOCATION,
    }
