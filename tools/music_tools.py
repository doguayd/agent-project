"""
Müzik Üretimi — Ziya için
===========================
ACE-Step ile lokal müzik üretimi.
GPU gerektirmez (CPU'da yavaş olur), RTX 4090'da hızlı çalışır.

Kurulum: pip install ace-step
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional


# ─── Genre & Stil Yardımcıları ────────────────────────────────────────────────

GENRE_MAP = {
    "pop":        "pop, catchy, modern production",
    "rock":       "rock, electric guitar, drums, energetic",
    "caz":        "jazz, piano, saxophone, swing, smooth",
    "jazz":       "jazz, piano, saxophone, swing, smooth",
    "klasik":     "classical, orchestral, strings, piano, symphony",
    "classical":  "classical, orchestral, strings, piano, symphony",
    "elektronik": "electronic, synthesizer, beats, EDM, dance",
    "electronic": "electronic, synthesizer, beats, EDM, dance",
    "hip-hop":    "hip-hop, rap, beats, urban, bass",
    "r&b":        "R&B, soul, smooth, rhythm and blues",
    "folk":       "folk, acoustic guitar, storytelling, warm",
    "country":    "country, acoustic, twang, guitar, storytelling",
    "metal":      "metal, heavy guitar, drums, powerful, aggressive",
    "ambient":    "ambient, atmospheric, calm, meditative, drone",
    "lofi":       "lofi, lo-fi hip hop, chill, study music, mellow",
    "flamenco":   "flamenco, Spanish guitar, passionate, traditional",
    "türkü":      "Turkish folk, saz, emotional, traditional, acoustic",
    "arabesk":    "arabesk, Turkish, emotional, oud, orchestral",
}

MOOD_MAP = {
    "mutlu":       "happy, uplifting, bright, cheerful",
    "hüzünlü":     "sad, melancholic, emotional, slow",
    "enerjik":     "energetic, powerful, driving, intense",
    "sakin":       "calm, peaceful, relaxing, gentle",
    "romantik":    "romantic, warm, loving, tender",
    "epik":        "epic, cinematic, powerful, grand, orchestral",
    "gizemli":     "mysterious, dark, atmospheric, suspenseful",
    "heyecanlı":   "exciting, thrilling, dynamic, fast",
    "melankolik":  "melancholic, bittersweet, nostalgic, emotional",
    "motivasyon":  "motivational, inspiring, uplifting, powerful",
}


def _build_prompt(description: str) -> tuple[str, str]:
    """
    Kullanıcı tanımından ACE-Step için tags ve lyrics üret.
    Returns: (tags, lyrics)
    """
    desc = description.lower()

    # Genre bul
    genre_tags = []
    for kw, tags in GENRE_MAP.items():
        if kw in desc:
            genre_tags.append(tags)
    if not genre_tags:
        genre_tags.append("instrumental, pleasant, melodic")

    # Mood bul
    mood_tags = []
    for kw, tags in MOOD_MAP.items():
        if kw in desc:
            mood_tags.append(tags)

    # Enstrüman bul
    instruments = []
    for inst in ["piyano", "piano", "gitar", "guitar", "keman", "violin",
                 "davul", "drums", "bas", "bass", "flüt", "flute",
                 "saksafon", "saxophone", "org", "organ", "synthesizer"]:
        if inst in desc:
            instruments.append(inst)

    # Tags birleştir
    all_tags = genre_tags + mood_tags + instruments
    tags = ", ".join(all_tags[:8])  # ACE-Step max tag

    # Söz (instrumental için boş bırak)
    lyrics = "[instrumental]" if not any(w in desc for w in ["söz", "lyrics", "şarkı sözü"]) else ""

    return tags, lyrics


async def generate_music(
    description:  str,
    duration_s:   int  = 30,
    output_dir:   str  = "workspace/music",
    filename:     Optional[str] = None,
) -> dict:
    """
    ACE-Step ile müzik üret.

    Returns:
        {
          "success": bool,
          "path": str,
          "duration": int,
          "tags": str,
          "error": str | None,
        }
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if not filename:
        ts = int(time.time())
        safe_name = "".join(c if c.isalnum() else "_" for c in description[:30])
        filename = f"music_{safe_name}_{ts}.wav"

    output_path = str(Path(output_dir) / filename)
    tags, lyrics = _build_prompt(description)

    try:
        # ACE-Step import dene
        try:
            from acestep.pipeline import ACEStepPipeline
        except ImportError:
            # ace-step kurulu değil — placeholder ses üret
            return await _generate_placeholder(description, output_path, tags)

        loop = asyncio.get_event_loop()

        def _run_pipeline():
            pipe = ACEStepPipeline()
            pipe(
                prompt=tags,
                lyrics=lyrics,
                audio_duration=duration_s,
                output_path=output_path,
            )

        await asyncio.wait_for(
            loop.run_in_executor(None, _run_pipeline),
            timeout=300.0,  # 5 dakika max
        )

        return {
            "success":  True,
            "path":     output_path,
            "duration": duration_s,
            "tags":     tags,
            "lyrics":   lyrics,
            "error":    None,
        }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "path":    None,
            "duration": duration_s,
            "tags":    tags,
            "error":   "Zaman aşımı (5 dakika). GPU yoksa çok yavaş olabilir.",
        }
    except Exception as e:
        return {
            "success": False,
            "path":    None,
            "duration": duration_s,
            "tags":    tags,
            "error":   str(e),
        }


async def _generate_placeholder(description: str, output_path: str, tags: str) -> dict:
    """
    ace-step kurulu değilse kurulum talimatı döndür.
    İleride AudioCraft (Meta) ile değiştirilebilir.
    """
    return {
        "success": False,
        "path":    None,
        "duration": 0,
        "tags":    tags,
        "error":   (
            "ace-step kurulu değil. Kurulum:\n"
            "  pip install ace-step\n"
            "Not: PyTorch + CUDA gerektirir. "
            "RTX 4090 ile mükemmel çalışır."
        ),
        "install_hint": "pip install ace-step",
        "description": description,
    }
