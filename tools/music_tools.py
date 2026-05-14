"""
Müzik Üretimi — Ziya için
===========================
Meta MusicGen (HuggingFace transformers) ile lokal müzik üretimi.
RTX 4090: 30s müzik ~15-30 saniyede üretilir.
CPU: çalışır ama yavaş (~5-10 dakika).

Model ilk çalıştırmada ~2GB indirilir (facebook/musicgen-medium).
Küçük model: facebook/musicgen-small (~300MB, daha hızlı, daha az kaliteli)

ace-step yerine tercih sebebi:
- Python 3.14 uyumlu (ace-step spaCy 3.8.4 gerektiriyor, 3.14 desteği yok)
- transformers zaten kurulu
- CUDA otomatik algılanır
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional


# ─── Genre & Stil Yardımcıları ────────────────────────────────────────────────

GENRE_MAP = {
    "pop":        "pop, catchy, modern production, radio-friendly",
    "rock":       "rock, electric guitar, drums, energetic",
    "caz":        "jazz, piano, saxophone, swing, smooth",
    "jazz":       "jazz, piano, saxophone, swing, smooth",
    "klasik":     "classical, orchestral, strings, piano, symphony",
    "classical":  "classical, orchestral, strings, piano, symphony",
    "elektronik": "electronic, synthesizer, beats, EDM, dance",
    "electronic": "electronic, synthesizer, beats, EDM, dance",
    "edm":        "EDM, electronic dance music, synthesizer, energetic",
    "hip-hop":    "hip-hop, rap, beats, urban, bass heavy",
    "r&b":        "R&B, soul, smooth, rhythm and blues, groovy",
    "folk":       "folk, acoustic guitar, storytelling, warm, intimate",
    "country":    "country, acoustic, twang, guitar, heartfelt",
    "metal":      "heavy metal, distorted guitar, drums, powerful, aggressive",
    "ambient":    "ambient, atmospheric, calm, meditative, drone, ethereal",
    "lofi":       "lofi hip hop, chill beats, mellow, study music, relaxing",
    "flamenco":   "flamenco, Spanish guitar, passionate, traditional, rhythmic",
    "türkü":      "Turkish folk music, saz, bağlama, emotional, traditional",
    "arabesk":    "arabesk, Turkish emotional music, oud, orchestral",
    "sinema":     "cinematic, film score, orchestral, epic, dramatic",
    "video game": "video game music, chiptune, 8-bit, retro, nostalgic",
    "oyun":       "video game music, cinematic, epic, adventurous",
}

MOOD_MAP = {
    "mutlu":       "happy, uplifting, bright, cheerful, joyful",
    "hüzünlü":     "sad, melancholic, emotional, slow, bittersweet",
    "enerjik":     "energetic, powerful, driving, intense, pumping",
    "sakin":       "calm, peaceful, relaxing, gentle, serene",
    "romantik":    "romantic, warm, loving, tender, intimate",
    "epik":        "epic, cinematic, powerful, grand, majestic, orchestral",
    "gizemli":     "mysterious, dark, atmospheric, suspenseful, eerie",
    "heyecanlı":   "exciting, thrilling, dynamic, fast-paced",
    "melankolik":  "melancholic, bittersweet, nostalgic, pensive",
    "motivasyon":  "motivational, inspiring, uplifting, powerful, triumphant",
    "meditasyon":  "meditation, zen, peaceful, healing, spa, nature sounds",
    "odaklanma":   "focus, concentration, study, ambient, minimal",
}


def _build_prompt(description: str) -> tuple[str, str]:
    """
    Kullanıcı tanımından MusicGen için tags ve lyrics üret.
    Returns: (tags, lyrics)
    """
    desc = description.lower()

    # Genre bul
    genre_tags = []
    for kw, tags in GENRE_MAP.items():
        if kw in desc:
            genre_tags.append(tags)
    if not genre_tags:
        genre_tags.append("pleasant, melodic, instrumental, high quality")

    # Mood bul
    mood_tags = []
    for kw, tags in MOOD_MAP.items():
        if kw in desc:
            mood_tags.append(tags)

    # Enstrüman bul
    instruments = []
    for inst in ["piyano", "piano", "gitar", "guitar", "keman", "violin",
                 "davul", "drums", "bas", "bass", "flüt", "flute",
                 "saksafon", "saxophone", "org", "organ", "synthesizer",
                 "arp", "harp", "korno", "trumpet", "trombon", "trombone",
                 "saz", "bağlama", "oud", "ud"]:
        if inst in desc:
            instruments.append(inst)

    # Tags birleştir
    all_tags = genre_tags + mood_tags + instruments
    tags = ", ".join(all_tags[:6])  # MusicGen için kısa tut

    # Söz (instrumental için boş bırak)
    lyrics = ""

    return tags, lyrics


# ─── MusicGen Wrapper ─────────────────────────────────────────────────────────

_model_cache: dict = {}   # Model cache (bir kez yükle, tekrar kullan)


def _get_musicgen(model_name: str = "facebook/musicgen-medium"):
    """MusicGen model ve processor'ı yükle (cache'ten veya HuggingFace'ten)."""
    if model_name in _model_cache:
        return _model_cache[model_name]

    try:
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.float16 if device == "cuda" else torch.float32

        print(f"[MusicGen] Model yükleniyor: {model_name} ({device}, dtype={dtype})")

        processor = AutoProcessor.from_pretrained(model_name)
        model     = MusicgenForConditionalGeneration.from_pretrained(
            model_name,
            dtype=dtype,            # torch_dtype deprecated → dtype kullan
            use_safetensors=True,   # model.safetensors kullan, pytorch_model.bin indirme
            low_cpu_mem_usage=True,
        )
        model = model.to(device)
        model.eval()

        _model_cache[model_name] = (processor, model, device)
        print(f"[MusicGen] Hazır! ({device.upper()}, VRAM kullanımı: "
              f"{torch.cuda.memory_allocated()/1e9:.1f}GB)" if device == "cuda" else
              f"[MusicGen] Hazır! (CPU)")
        return processor, model, device

    except torch.cuda.OutOfMemoryError:
        # VRAM yetersiz — CPU'ya düş
        print(f"[MusicGen] CUDA OOM! CPU moduna geçiliyor...")
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
        processor = AutoProcessor.from_pretrained(model_name)
        model = MusicgenForConditionalGeneration.from_pretrained(
            model_name, dtype=torch.float32, use_safetensors=True, low_cpu_mem_usage=True
        )
        model.eval()
        _model_cache[model_name] = (processor, model, "cpu")
        print("[MusicGen] CPU modunda hazır (yavaş çalışacak)")
        return processor, model, "cpu"
    except Exception as e:
        raise RuntimeError(f"MusicGen yüklenemedi: {e}") from e


def _tokens_for_duration(duration_s: int, tokens_per_second: float = 50.0) -> int:
    """
    İstenen süre için gereken token sayısı.
    MusicGen: ~50 token/saniye (EnCodec compression rate ile değişir).
    """
    return max(128, int(duration_s * tokens_per_second))


def _run_musicgen(
    tags:       str,
    duration_s: int,
    output_path: str,
    model_name: str = "facebook/musicgen-medium",
) -> str:
    """Senkron MusicGen pipeline (executor'da çalışır)."""
    import torch
    import scipy.io.wavfile
    import numpy as np

    print(f"[MusicGen] _run_musicgen başlıyor: model={model_name}, tags='{tags[:80]}', dur={duration_s}s")

    processor, model, device = _get_musicgen(model_name)

    # Prompt hazırla
    inputs = processor(
        text           = [tags],
        padding        = True,
        return_tensors = "pt",
    ).to(device)

    max_tokens = _tokens_for_duration(duration_s)

    print(f"[MusicGen] Üretiliyor: '{tags[:80]}' — {duration_s}s ({max_tokens} token, device={device})")

    try:
        with torch.inference_mode():
            audio_values = model.generate(
                **inputs,
                max_new_tokens = max_tokens,
                do_sample      = True,
                guidance_scale = 3.0,
                temperature    = 1.0,
            )
    except torch.cuda.OutOfMemoryError:
        # CUDA OOM — önbelleği temizle ve CPU'da tekrar dene
        print("[MusicGen] CUDA OOM hatası! Model cache temizleniyor...")
        torch.cuda.empty_cache()
        if model_name in _model_cache:
            del _model_cache[model_name]
        raise RuntimeError("CUDA bellek yetersiz. Sunucu yeniden başlatın.")

    print(f"[MusicGen] generate() tamamlandı, audio_values shape: {audio_values.shape}")

    # Kaydet
    sampling_rate = model.config.audio_encoder.sampling_rate
    audio_np      = audio_values[0, 0].cpu().float().numpy()

    print(f"[MusicGen] audio_np shape={audio_np.shape}, min={audio_np.min():.3f}, max={audio_np.max():.3f}")

    # Normalize
    peak = max(abs(float(audio_np.max())), abs(float(audio_np.min())))
    if peak > 1e-6:
        audio_np = audio_np / peak * 0.95

    # int16'ya çevir (WAV için)
    audio_int16 = (audio_np * 32767).astype(np.int16)

    scipy.io.wavfile.write(output_path, rate=sampling_rate, data=audio_int16)
    print(f"[MusicGen] Kaydedildi: {output_path} ({sampling_rate}Hz, {len(audio_int16)} samples)")
    return output_path


async def generate_music(
    description: str,
    duration_s:  int  = 30,
    output_dir:  str  = "workspace/music",
    filename:    Optional[str] = None,
    model_name:  str  = "facebook/musicgen-medium",
) -> dict:
    """
    MusicGen ile müzik üret.

    Returns:
        {
          "success": bool,
          "path": str | None,
          "duration": int,
          "tags": str,
          "error": str | None,
        }
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if not filename:
        ts        = int(time.time())
        safe_name = "".join(c if c.isalnum() else "_" for c in description[:30])
        filename  = f"music_{safe_name}_{ts}.wav"

    output_path = str(Path(output_dir) / filename)
    tags, _     = _build_prompt(description)

    # Büyük model kurulu değilse küçüğe düş
    if model_name == "facebook/musicgen-medium":
        # small modeli dene önce (daha hızlı yanıt, model cache'te değilse)
        # medium daha kaliteli; ilk kullanımda ~2GB indirir
        pass

    try:
        # Executor'da çalıştır — event loop'u bloklamaz
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _run_musicgen(tags, duration_s, output_path, model_name),
            ),
            timeout=600.0,  # 10 dakika max (büyük model + CPU)
        )

        return {
            "success":  True,
            "path":     output_path,
            "duration": duration_s,
            "tags":     tags,
            "lyrics":   "",
            "error":    None,
        }

    except asyncio.TimeoutError:
        return {
            "success":  False,
            "path":     None,
            "duration": duration_s,
            "tags":     tags,
            "error":    "Zaman aşımı (10 dakika). CPU modda çok yavaş olabilir.",
        }
    except ImportError as e:
        return {
            "success":  False,
            "path":     None,
            "duration": duration_s,
            "tags":     tags,
            "error":    (
                f"transformers kurulu değil: {e}\n"
                "Kurulum: pip install transformers accelerate scipy"
            ),
            "install_hint": "pip install transformers accelerate scipy",
        }
    except Exception as e:
        return {
            "success":  False,
            "path":     None,
            "duration": duration_s,
            "tags":     tags,
            "error":    str(e),
        }


async def _generate_placeholder(description: str, output_path: str, tags: str) -> dict:
    """Kullanılmıyor artık — MusicGen her zaman denenecek."""
    return await generate_music(description, output_dir=str(Path(output_path).parent))
