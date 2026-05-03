import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Anahtarları ────────────────────────────────────────────────────────
GOOGLE_API_KEY      = os.getenv("GOOGLE_API_KEY", "")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")  # Distance Matrix API
OLLAMA_HOST       = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ─── Supervisor Modu ────────────────────────────────────────────────────────
# "auto"   → İnternet varsa Gemini, yoksa en iyi yerel model
# "gemini" → Yalnızca Gemini
# "claude" → Yalnızca Claude (ANTHROPIC_API_KEY gerekli)
# "ollama" → Yalnızca yerel
SUPERVISOR_PROVIDER = os.getenv("SUPERVISOR_PROVIDER", "auto")

# ─── Offline Supervisor Öncelik Sırası (Nisan 2026) ─────────────────────────
# Sistem: RTX 4090 Laptop 16 GB VRAM | 32 GB RAM | Intel Core Ultra 9 185H
# Sadece kurulu modeller listede — `ollama list` çıktısına göre güncellendi
LOCAL_SUPERVISOR_PRIORITY: list[str] = [
    # ── Hızlı + Güçlü (tam GPU, ~9 GB) ─────────────────────────────────────
    "qwen3:14b",               # ★★★ KURULU | 9.3 GB | ~45 tok/s | thinking modu
                               #      JSON planlama mükemmel, genel+Türkçe
    # ── Kaliteli (kısmen RAM offload) ───────────────────────────────────────
    "gpt-oss:20b",             # ★★  KURULU | 13 GB  | güçlü genel, OpenAI açık
    "gemma4:26b",              # ★★  KURULU | 17 GB  | MoE Google, multimodal
    # ── Büyük (24 GB — CPU+GPU split, yavaş ama güçlü) ──────────────────────
    "nemotron-cascade-2:30b",  # ★   KURULU | 24 GB  | 182s plan süresi — fazla büyük
    "nemotron-3-nano:30b",     # ★   KURULU | 24 GB  | büyük, yedek
    # ── Hızlı Yedekler ──────────────────────────────────────────────────────
    "phi4:14b",                # ✓   KURULU | 9.1 GB | hızlı, iyi JSON
    "deepseek-r1:14b",         # ✓   KURULU | 9.0 GB | reasoning iyi ama <think> yavaş
    "qwen2.5-coder:14b",       # ✓   KURULU | 9.0 GB | coder model ama çalışır
    "gemma3:12b",              # ✓   KURULU | 8.1 GB | yedek
    "llama3.1:8b",             # ✓   KURULU | 4.9 GB | son çare
    "qwen2.5:7b-instruct",     # ✓   KURULU | 4.7 GB | acil yedek
]

# ── Önerilen Yeni İndirmeler ──────────────────────────────────────────────────
# ollama pull qwen3-coder:30b    → ★★★ Kenji için ideal, MoE ~12GB (henüz yok)
# ollama pull devstral-small-2   → ★★  Hafif coder, SWE-bench 46.8%, ~5GB
# ollama pull magistral-small:24b → ★★ AIME 70.7% reasoning, ~15GB

# ─── Model Konfigürasyonları ────────────────────────────────────────────────
MODELS: dict[str, dict] = {
    "supervisor": {
        "provider":    "gemini",           # runtime'da auto_select_supervisor() değiştirir
        "model":       "gemini-2.0-flash",
        "temperature": 0.25,
        "description": "Planlama, yönlendirme ve değerlendirme",
        "persona":     "Mila",
    },

    # ── Kenji (Coder) ────────────────────────────────────────────────────────
    # qwen2.5-coder:14b kurulu ve güvenilir — qwen3-coder:30b gelince değiştir
    "coder": {
        "provider":    "ollama",
        "model":       os.getenv("CODER_MODEL", "qwen2.5-coder:14b"),
        "temperature": 0.1,
        "description": "Üretim kaliteli kod yazımı",
        "persona":     "Kenji",
    },

    # ── Rex (Reviewer) ───────────────────────────────────────────────────────
    "reviewer": {
        "provider":    "ollama",
        "model":       os.getenv("REVIEWER_MODEL", "qwen2.5-coder:14b"),
        "temperature": 0.1,
        "description": "Kod inceleme, güvenlik ve kalite",
        "persona":     "Rex",
    },

    # ── Zara (Tester) ────────────────────────────────────────────────────────
    "tester": {
        "provider":    "ollama",
        "model":       os.getenv("TESTER_MODEL", "qwen2.5-coder:14b"),
        "temperature": 0.1,
        "description": "Kapsamlı test yazımı",
        "persona":     "Zara",
    },

    # ── Aria (Researcher) ────────────────────────────────────────────────────
    # qwen3:14b kurulu ve mükemmel — thinking modu ile derin araştırma
    "researcher": {
        "provider":    "ollama",
        "model":       os.getenv("RESEARCHER_MODEL", "qwen3:14b"),
        "temperature": 0.35,
        "description": "Gereksinim analizi ve araştırma",
        "persona":     "Aria",
    },

    # ── Neo (Debugger) ───────────────────────────────────────────────────────
    "debugger": {
        "provider":    "ollama",
        "model":       os.getenv("DEBUGGER_MODEL", "deepseek-r1:14b"),
        "temperature": 0.05,
        "description": "Hata ayıklama ve kök neden analizi",
        "persona":     "Neo",
    },

    # ── Hızlı görevler ──────────────────────────────────────────────────────
    "fast": {
        "provider":    "ollama",
        "model":       os.getenv("FAST_MODEL", "qwen2.5-coder:1.5b-base"),
        "temperature": 0.1,
        "description": "Hızlı, basit görevler",
        "persona":     "",
    },
}

# ─── Sistem & Sunucu Ayarları ────────────────────────────────────────────────
WORKSPACE_DIR  = os.getenv("WORKSPACE_DIR", "workspace")
CHROMA_PATH    = os.getenv("CHROMA_PATH",   "./chroma_db")
WS_HOST        = os.getenv("WS_HOST",       "0.0.0.0")
WS_PORT        = int(os.getenv("WS_PORT",   "8000"))
MAX_CTX_CHARS  = 16_000   # gemma4:26b 128K ctx — safely use much more per agent
MAX_PARALLEL   = 4
