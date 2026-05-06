"""
Music Agent — Ziya
===================
Persona : Yaratıcı, duygusal, müzikal bir sanatçı AI.
Görevi  : Kullanıcının tanımından lokal olarak müzik üretir.
          ACE-Step kullanır (pip install ace-step).
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from config import MODELS
from core.events import Emitter, noop, wrap
from core.llm_client import create_llm
from agents.base_agent import _strip_think_blocks
from tools.music_tools import generate_music, _build_prompt, GENRE_MAP, MOOD_MAP


class MusicAgent:
    """
    Müzik üretimi:
    1. Kullanıcı tanımını analiz eder
    2. ACE-Step tag ve lyrics üretir
    3. Lokal GPU ile müzik üretir
    """

    def __init__(self) -> None:
        cfg = MODELS.get("supervisor", MODELS["fast"])
        self.llm = create_llm(
            cfg["provider"],
            cfg["model"],
            temperature=0.7,  # Müzik için daha yaratıcı
        )

    async def _enhance_prompt(self, description: str) -> str:
        """LLM ile kullanıcı tanımını zenginleştir."""
        prompt = f"""Kullanıcı şu müziği istiyor: "{description}"

Bu müzik için ACE-Step audio generation modeline uygun kısa İngilizce tag listesi oluştur.
Örnek format: "jazz, piano, saxophone, melancholic, slow tempo, 1950s style"

Sadece virgülle ayrılmış tagları yaz, başka bir şey ekleme."""

        msgs = [{"role": "user", "content": prompt}]
        try:
            raw = await self.llm.generate(msgs)
            enhanced = _strip_think_blocks(raw).strip()
            # Sadece tag formatı olduğundan emin ol
            if len(enhanced) < 200 and "," in enhanced:
                return enhanced
        except Exception:
            pass
        return ""

    async def create(
        self,
        query:       str,
        emit:        Emitter = noop,
        duration_s:  int = 30,
    ) -> dict:
        """
        Ana müzik üretim metodu.

        Returns:
            {
              "success": bool,
              "path": str | None,
              "duration": int,
              "tags": str,
              "summary": str,
              "elapsed_s": float,
            }
        """
        t0 = time.perf_counter()

        await emit(wrap("music.status", {
            "step": "parse", "message": "Müzik tanımı analiz ediliyor..."
        }))

        # Süre tespit et
        dur_m = re.search(r"(\d+)\s*(?:saniyelik|saniye|second|sn)", query, re.IGNORECASE)
        if dur_m:
            duration_s = min(int(dur_m.group(1)), 120)  # Max 2 dakika

        # LLM ile prompt zenginleştir (opsiyonel, hata olursa basic prompt kullan)
        await emit(wrap("music.status", {
            "step": "prompt", "message": "Müzik tagları hazırlanıyor..."
        }))

        enhanced_tags = await self._enhance_prompt(query)
        tags, lyrics  = _build_prompt(query)

        if enhanced_tags:
            tags = enhanced_tags

        await emit(wrap("music.status", {
            "step":     "generate",
            "message":  f"Müzik üretiliyor ({duration_s}s)... Bu birkaç dakika sürebilir.",
            "tags":     tags,
            "duration": duration_s,
        }))

        result = await generate_music(
            description=query,
            duration_s=duration_s,
        )

        elapsed = round(time.perf_counter() - t0, 1)

        if result["success"]:
            summary = (
                f"✅ Müzik başarıyla üretildi! ({elapsed}s)\n"
                f"Stil: {tags[:100]}\n"
                f"Dosya: {result['path']}"
            )
        else:
            err = result.get("error", "Bilinmeyen hata")
            if "install" in err.lower() or "install_hint" in result:
                summary = (
                    f"🎵 Müzik üretici bağımlılıkları eksik.\n\n"
                    f"Kurulum için terminalde:\n"
                    f"```\npip install transformers accelerate scipy\n```\n\n"
                    f"RTX 4090'ın ile {duration_s}s müzik ~20-30 saniyede üretilir.\n"
                    f"Model ilk çalıştırmada ~1.5GB indirilir (facebook/musicgen-medium)."
                )
            else:
                summary = f"Müzik üretimi başarısız: {err}"

        await emit(wrap("music.done", {
            "success":   result["success"],
            "path":      result.get("path"),
            "tags":      tags,
            "elapsed_s": elapsed,
            "summary":   summary,
        }))

        return {
            "success":   result["success"],
            "path":      result.get("path"),
            "duration":  duration_s,
            "tags":      tags,
            "summary":   summary,
            "elapsed_s": elapsed,
        }
