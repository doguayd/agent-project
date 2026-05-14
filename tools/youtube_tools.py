"""
YouTube Kanal İstatistikleri
=============================
YouTube Data API v3 ile public kanal raporu.
API anahtarı: config.GOOGLE_API_KEY (YouTube Data API etkin olmalı)

JARVIS (Alp Ünlü, @alppunlu) projesinden uyarlanmıştır.
"""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse

import requests

from config import GOOGLE_API_KEY


API_ROOT     = "https://www.googleapis.com/youtube/v3"
TIMEOUT      = 14
CHANNEL_ID_RE = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
ISO_DUR_RE    = re.compile(r"PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?")


def _fmt_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _parse_duration_s(raw: str) -> int:
    m = ISO_DUR_RE.match(raw or "")
    if not m:
        return 0
    return int(m.group("h") or 0)*3600 + int(m.group("m") or 0)*60 + int(m.group("s") or 0)


def _fmt_duration(raw: str) -> str:
    total = _parse_duration_s(raw)
    if total <= 0:
        return ""
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}s {mins}dk"
    return f"{mins}dk {secs:02d}sn" if mins else f"{secs}sn"


def _parse_dt(raw: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _days_ago(published_at: str) -> str:
    published = _parse_dt(published_at)
    if not published:
        return ""
    delta = dt.datetime.now(dt.timezone.utc) - published.astimezone(dt.timezone.utc)
    days = max(0, delta.days)
    if days == 0:
        return "bugün"
    if days == 1:
        return "dün"
    return f"{days} gün önce"


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _normalize_channel_ref(raw: str) -> tuple[str | None, str]:
    value = str(raw or "").strip()
    if not value:
        return None, ""
    if value.startswith("@"):
        return "forHandle", value
    if CHANNEL_ID_RE.match(value):
        return "id", value
    if value.startswith("http"):
        parsed = urlparse(value)
        if parsed.netloc.lower() in YOUTUBE_HOSTS:
            path = parsed.path.strip("/")
            if path.startswith("@"):
                return "forHandle", path
            if path.startswith("channel/"):
                cid = path.split("/", 1)[1].strip()
                if cid:
                    return "id", cid
    return "forHandle", value if value.startswith("@") else f"@{value}"


def _api_get(endpoint: str, params: dict) -> dict:
    api_key = GOOGLE_API_KEY
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY tanımlı değil. YouTube istatistikleri için gerekli.")
    resp = requests.get(
        f"{API_ROOT}/{endpoint}",
        params={**params, "key": api_key},
        timeout=TIMEOUT,
        headers={"User-Agent": "Atlas/1.0"},
    )
    if resp.ok:
        return resp.json()
    try:
        err = resp.json().get("error", {})
    except Exception:
        err = {}
    reasons = err.get("errors") or []
    reason  = reasons[0].get("reason", "") if reasons and isinstance(reasons[0], dict) else ""
    if reason == "keyInvalid":
        raise RuntimeError("YouTube API anahtarı geçersiz.")
    if reason == "quotaExceeded":
        raise RuntimeError("YouTube API kotası doldu.")
    raise RuntimeError(err.get("message") or f"YouTube API hatası ({resp.status_code}).")


def _fetch_channel(handle: str) -> tuple[dict, str]:
    filter_name, filter_value = _normalize_channel_ref(handle)
    if not filter_name:
        raise RuntimeError("Geçerli bir YouTube kanal handle'ı veya ID'si gerekli (@handle veya UCxxxxxx).")
    payload = _api_get("channels", {
        "part": "snippet,statistics,contentDetails",
        filter_name: filter_value,
        "maxResults": 1,
    })
    items = payload.get("items") or []
    if not items:
        raise RuntimeError(f"'{filter_value}' kanalı bulunamadı.")
    return items[0], filter_value


def _fetch_videos(uploads_id: str, limit: int) -> list[dict]:
    pl = _api_get("playlistItems", {
        "part": "snippet,contentDetails",
        "playlistId": uploads_id,
        "maxResults": max(1, min(10, limit)),
    })
    items = pl.get("items") or []
    if not items:
        return []

    by_id, ordered = {}, []
    for item in items:
        snippet = item.get("snippet") or {}
        details = item.get("contentDetails") or {}
        vid = details.get("videoId") or (snippet.get("resourceId") or {}).get("videoId")
        if not vid:
            continue
        ordered.append(vid)
        by_id[vid] = {"video_id": vid, "title": snippet.get("title", ""), "published_at": snippet.get("publishedAt", "")}

    if not ordered:
        return []

    vdata = _api_get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ordered)})
    for item in vdata.get("items") or []:
        vid = item.get("id", "")
        if vid not in by_id:
            continue
        stats = item.get("statistics") or {}
        by_id[vid].update({
            "title": (item.get("snippet") or {}).get("title") or by_id[vid]["title"],
            "views": int(stats.get("viewCount") or 0),
            "likes": int(stats.get("likeCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "duration": (item.get("contentDetails") or {}).get("duration", ""),
        })
    return [by_id[v] for v in ordered if v in by_id]


def get_youtube_channel_report(query: str = "overview", handle: str = "", video_limit: int = 6) -> str:
    """
    Kanal istatistikleri + son video performansı.
    handle: @username | UCxxxxxx | YouTube URL
    """
    if not GOOGLE_API_KEY:
        return (
            "YouTube istatistikleri için GOOGLE_API_KEY gerekli "
            "(YouTube Data API v3 etkin olmalı)."
        )
    try:
        channel, ref = _fetch_channel(handle)
        snippet    = channel.get("snippet") or {}
        stats      = channel.get("statistics") or {}
        uploads_id = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads", "")

        title       = snippet.get("title", "Kanal")
        custom_url  = (snippet.get("customUrl") or "").strip()
        display     = custom_url if custom_url.startswith("@") else ref
        subscribers = int(stats.get("subscriberCount") or 0)
        total_views = int(stats.get("viewCount") or 0)
        video_count = int(stats.get("videoCount") or 0)

        videos = _fetch_videos(uploads_id, video_limit) if uploads_id else []
        valid  = [v for v in videos if v.get("title") and v.get("title") != "Private video"]

        parts = [
            f"{title} kanalı: {_fmt_int(subscribers)} abone, "
            f"{_fmt_int(total_views)} toplam izlenme, {_fmt_int(video_count)} video."
        ]
        if display:
            parts.append(f"Handle: {display}")

        if valid:
            avg_v = round(_avg([v.get("views", 0) for v in valid]))
            avg_l = round(_avg([v.get("likes", 0) for v in valid]))
            avg_c = round(_avg([v.get("comments", 0) for v in valid]))
            parts.append(
                f"Son {len(valid)} video ortalaması: {_fmt_int(avg_v)} izlenme, "
                f"{_fmt_int(avg_l)} beğeni, {_fmt_int(avg_c)} yorum."
            )

            best = max(valid, key=lambda v: v.get("views", 0))
            tail = [t for t in [_days_ago(best.get("published_at", "")), _fmt_duration(best.get("duration", ""))] if t]
            parts.append(
                f"En iyi video: '{best.get('title')}' — {_fmt_int(best.get('views', 0))} izlenme"
                + (f" ({', '.join(tail)})" if tail else "") + "."
            )

            # Yayın sıklığı
            dates = [_parse_dt(v.get("published_at", "")) for v in valid]
            dates = [d for d in dates if d]
            if len(dates) >= 2:
                gaps = [(later - earlier).total_seconds() / 86400
                        for earlier, later in zip(dates[1:], dates[:-1])]
                parts.append(f"Ortalama yayın sıklığı: {sum(gaps)/len(gaps):.1f} günde bir.")

            # Trend
            if len(valid) >= 4:
                split  = max(2, len(valid) // 2)
                recent_avg = _avg([v.get("views", 0) for v in valid[:split]])
                older_avg  = _avg([v.get("views", 0) for v in valid[split:]])
                if older_avg > 0:
                    ratio = recent_avg / older_avg
                    if ratio >= 1.18:
                        parts.append("Son videolar yükselen trend gösteriyor ✅")
                    elif ratio <= 0.82:
                        parts.append("Son videolarda izlenme düşüşü var ⚠️")

            # Detay istendiyse liste
            if any(w in query.lower() for w in ("detay", "analiz", "rapor", "liste", "son video")):
                rows = []
                for i, v in enumerate(valid[:3], 1):
                    age = _days_ago(v.get("published_at", ""))
                    rows.append(
                        f"{i}. {v.get('title')} — {_fmt_int(v.get('views', 0))} izlenme, "
                        f"{_fmt_int(v.get('likes', 0))} beğeni"
                        + (f" ({age})" if age else "")
                    )
                parts.append("Son videolar:\n" + "\n".join(rows))

        parts.append("Not: İzlenme süresi, CTR ve gelir verileri Studio erişimi gerektiriyor.")
        return "\n".join(parts)

    except Exception as exc:
        return f"YouTube istatistikleri alınamadı: {exc}"
