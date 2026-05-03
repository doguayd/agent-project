# ⚡ Multi-Agent Kodlama Sistemi

> **Donanıma Özel Optimize Edildi**
> Intel Core Ultra 9 185H · 32GB LPDDR5X · RTX 4090 Laptop 16GB VRAM · CUDA 13.2

Çok katmanlı, paralel çalışabilen yapay zeka ajan sistemi.
Bir **Supervisor** (Gemini 2.0 Flash veya yerel model) ile yönlendirilen uzman yerel ajanlardan oluşur.
Gerçek zamanlı Web UI, ChromaDB vector bellek ve tam offline desteği içerir.

---

## 🗂 Proje Durumu

| Aşama | Durum | Açıklama |
|-------|-------|----------|
| Phase 1 | ✅ Tamamlandı | Mimari, core modeller, LLM soyutlaması |
| Phase 2 | ✅ Tamamlandı | 6 uzman ajan + persona sistemi |
| Phase 3 | ✅ Tamamlandı | Orkestratör, paralel yürütme |
| Phase 4 | ✅ Tamamlandı | CLI giriş noktası, sağlık kontrolü |
| Phase 5 | ✅ Tamamlandı | Gerçek zamanlı Web UI (FastAPI + WebSocket) |
| Phase 6 | ✅ Tamamlandı | Vector bellek (ChromaDB + nomic-embed-text) |
| Phase 7 | 🔜 Sonraki | Workspace dosya yönetimi, kod çalıştırma |
| Phase 8 | 🔜 Sonraki | Çoklu oturum yönetimi, proje hafızası |

---

## 🏗 Mimari

```
Kullanıcı Görevi
      │
      ▼
┌────────────────────────────────────────────────────────┐
│                  SUPERVISOR — Mila                     │
│   Online:  Gemini 2.0 Flash  (Google Pro)             │
│   Offline: qwen2.5-coder:14b / deepseek-r1:14b        │
│                                                        │
│   1. PLANLA   → görevi alt görevlere böl               │
│   2. ATAN     → uygun uzmanlara dağıt                  │
│   3. DEĞERLENDİR → sonuçları analiz et                │
│   4. SENTEZLİ → nihai yanıtı üret                     │
└───────────────────────┬────────────────────────────────┘
                        │  ExecutionPlan (JSON)
                        ▼
┌────────────────────────────────────────────────────────┐
│                   ORKESTRATÖR                          │
│   • parallel_group'a göre sıralar                      │
│   • asyncio.gather ile paralel çalıştırır             │
│   • Bağımlılık bağlamını otomatik enjekte eder        │
│   • Vector bellek: geçmiş çek + oturum kaydet         │
└──┬──────┬──────┬──────┬──────┬─────────────────────────┘
   │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼
[Aria] [Kenji] [Rex] [Zara] [Neo]
Rsrch  Coder  Revw  Test  Debug
   │      │      │      │      │
   └──────┴──────┴──────┴──────┘
        Ollama (GPU / CPU auto)
              │
              ▼
         ChromaDB
       (Vector Bellek)
```

### Paralel Yürütme Örneği

```
Grup 0 (tek): [Aria — Researcher]
                 │ bağımlılık enjeksiyonu
Grup 1 (tek): [Kenji — Coder]
                 │
Grup 2 (paralel): [Rex — Reviewer]  [Zara — Tester]  ← aynı anda
                 │
Supervisor — Mila: Tüm sonuçları değerlendirir + sentezler
```

---

## 🤖 Ajan Ekibi

| Ajan | Persona | Model | VRAM | Görev |
|------|---------|-------|------|-------|
| **Supervisor** | Mila | Gemini Flash / qwen2.5-coder:14b | — / ~9GB | Plan + değerlendirme |
| **Researcher** | Aria | gemma3:12b | ~8GB | Gereksinim analizi, araştırma |
| **Coder** | Kenji | qwen2.5-coder:14b | ~9GB | Üretim kaliteli kod |
| **Reviewer** | Rex | qwen2.5-coder:14b | ~9GB | Kod inceleme, güvenlik |
| **Tester** | Zara | qwen2.5-coder:14b | ~9GB | Kapsamlı test yazımı |
| **Debugger** | Neo | qwen2.5-coder:14b | ~9GB | Hata ayıklama |

### Persona Özellikleri

| Persona | Karakter | Motto |
|---------|---------|-------|
| **Mila** (Supervisor) | Soğukkanlı, stratejik mimar | "Belirsizlik planın düşmanıdır." |
| **Aria** (Researcher) | Meraklı, analitik | "Cevap vermeden önce her şeyi öğrenirim." |
| **Kenji** (Coder) | Sessiz mükemmelliyetçi | "Çalışan kod değil, güzel ve çalışan kod." |
| **Rex** (Reviewer) | Eleştirel, toleranssız | "Bir bug bile geçemez gözümden." |
| **Zara** (Tester) | Metodolojik, şüpheci | "Her şeyi kırmaya çalışırım." |
| **Neo** (Debugger) | Dedektif, iz takipçisi | "Hatanın sebebini bulmak asıl zorluktur." |

---

## 🌐 Supervisor Otomatik Seçimi

```
İnternet var + GOOGLE_API_KEY  →  Gemini 2.0 Flash (bulut, hızlı)
İnternet var + ANTHROPIC_API_KEY  →  Claude Sonnet (bulut)
İnternet yok  →  Yerel model (öncelik sırası):
    1. deepseek-r1:14b   ★ En iyi reasoning  (~9.5GB) [İNDİR]
    2. phi4:14b          ★ Hızlı + güçlü     (~9.0GB) [İNDİR]
    3. qwen2.5-coder:14b ✓ Mevcut, JSON mükemmel
    4. gpt-oss:20b       ✓ Mevcut, güçlü
    5. gemma3:12b        ✓ Mevcut, yedek
    6. llama3.1:8b       ✓ Mevcut, son çare
```

> `SUPERVISOR_PROVIDER=auto` (varsayılan) — her başlangıçta otomatik karar verir.

---

## 📁 Dosya Yapısı

```
Agent_Project/
├── main.py              # CLI giriş noktası
├── server.py            # FastAPI + WebSocket sunucusu
├── orchestrator.py      # Paralel görev yöneticisi
├── config.py            # Model & sistem ayarları
├── requirements.txt     # Python bağımlılıkları
├── .env.example         # API anahtarı şablonu
│
├── agents/
│   ├── supervisor.py    # Mila — Yönetici-Planlayıcı
│   ├── coder.py         # Kenji — Kod yazımı
│   ├── reviewer.py      # Rex — Kod inceleme
│   ├── tester.py        # Zara — Test yazımı
│   ├── researcher.py    # Aria — Araştırma
│   ├── debugger.py      # Neo — Hata ayıklama
│   └── base_agent.py    # Ortak temel sınıf (streaming)
│
├── core/
│   ├── llm_client.py    # Ollama/Gemini/Claude soyutlaması
│   ├── models.py        # Pydantic veri modelleri
│   ├── memory.py        # Konuşma hafızası
│   ├── events.py        # WebSocket event sistemi
│   └── vector_memory.py # ChromaDB geçmiş bellek
│
├── tools/
│   ├── file_tools.py    # Workspace dosya okuma/yazma
│   └── code_executor.py # Python & pytest çalıştırıcı
│
├── static/
│   └── index.html       # Gerçek zamanlı Web UI (dark theme)
│
├── workspace/           # Üretilen dosyalar
└── chroma_db/           # Vector bellek (otomatik oluşur)
```

---

## 🚀 Kurulum

### 1. Bağımlılıkları Yükle

```bash
pip install -r requirements.txt
```

### 2. API Anahtarını Ayarla

```bash
cp .env.example .env
# .env dosyasını düzenle: GOOGLE_API_KEY değerini gir
```

Google API anahtarı: https://aistudio.google.com/apikey

### 3. Ollama'yı Başlat

```bash
ollama serve
```

### 4. Çalıştır

```bash
# Sistem kontrolü
python main.py --check

# Web UI (önerilen)
python main.py --web
# → http://localhost:8000

# CLI etkileşimli
python main.py

# Tek görev
python main.py "Python ile binary search tree uygula"
```

---

## 💻 Web UI Özellikleri

- **Gerçek zamanlı streaming**: Her ajanın çıktısı token token akar
- **Ajan kartları**: Persona, durum, geçen süre, model bilgisi
- **Plan vizualizasyonu**: Paralel gruplar görsel olarak gösterilir
- **Sistem logu**: Tüm eventler zaman damgalı terminal görünümünde
- **Çevrimdışı göstergesi**: Supervisor modeli otomatik güncellenir
- **Görev geçmişi**: Son 8 görev tıklanabilir listede

---

## 📥 Önerilen Ek Modeller

```bash
# Offline supervisor için en iyi seçenekler (RTX 4090'a sığar)
ollama pull deepseek-r1:14b   # ~9.5GB — reasoning/planlama
ollama pull phi4:14b          # ~9.0GB — hızlı + güçlü
```

---

## ⚙ Ortam Değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|---------|
| `GOOGLE_API_KEY` | — | Gemini API (online supervisor) |
| `ANTHROPIC_API_KEY` | — | Claude API (isteğe bağlı) |
| `SUPERVISOR_PROVIDER` | `auto` | `auto` / `gemini` / `claude` / `ollama` |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama adresi |
| `CODER_MODEL` | `qwen2.5-coder:14b` | Kodlama modeli |
| `RESEARCHER_MODEL` | `gemma3:12b` | Araştırma modeli |
| `WS_PORT` | `8000` | Web UI portu |
| `CHROMA_PATH` | `./chroma_db` | Vector bellek dizini |

---

## 🖥 Donanım Notları

| Senaryo | Davranış |
|---------|---------|
| RTX 4090 aktif | `qwen2.5-coder:14b` (~9GB) tamamen GPU'da çalışır |
| RTX 4090 kapalı (şarj tasarrufu) | Ollama otomatik CPU moduna geçer — hata vermez |
| İnternet var + API key | Gemini Flash supervisor (~100ms yanıt) |
| İnternet yok | En iyi yerel model otomatik seçilir |

---

## 📝 Değişiklik Geçmişi

### v0.8.0 — 2026-04-11
- **Coder görsel zorunlulukları**: CSS değişkenleri, gradient kartlar, sticky navbar, Google Fonts,
  animasyonlar, gerçek içerik (min 6 öğe) — gri/beyaz iskelet çıktısı artık yasak
- **Researcher görsel tasarım kılavuzu**: Renk paleti, gradient değerleri, tipografi, spacing
  artık araştırma çıktısında spesifik olarak belirtilmek zorunda
- **Auto-reviewer enjeksiyonu**: Plan'da coder var ama reviewer yoksa orchestrator otomatik
  `t_rev_auto` görevi ekler; artık her kodlama görevinin arkasında kalite kontrol var
- **`_enrich_plan` Türkçe sorunu giderildi**: Hedeften yalnızca ASCII kelimeler çıkarılıyor;
  tanınan Türkçe anahtar kelimeler İngilizce'ye map ediliyor (tatil→travel, alışveriş→shopping vb.)
- **Researcher modeli**: `qwen2.5-coder:14b` → `gpt-oss:20b` (daha yaratıcı, daha güçlü mimari analiz)
- **Offline model önerileri güncellendi**: `phi4-reasoning:14b` (en iyi supervisor) ve `qwen3:14b`
  öncelik listesine eklendi; indirme komutları config.py'de belgelendi

### v0.7.0 — 2026-04-11
- **Otomatik dosya kaydetme**: Coder çıktısından `### filename.ext ###` ve ` ```lang ``` ` blokları parse edilerek `workspace/{proje_slug}/` altına otomatik kaydedilir
- **Workspace paneli (UI)**: Sidebar'da kayıtlı dosyalar listelenir; tıklayınca içerik görüntüleyici açılır (kopyala butonu dahil)
- **Dosya yükleme (UI)**: 📎 butonu ile istenen dosyaları workspace'e yükleyebilirsin; bağlam olarak ajanlara iletilebilir
- **Yeni API endpoint'leri**: `GET /workspace/files`, `GET /workspace/read?path=`, `POST /workspace/upload`
- **Gemini 2.5 Flash**: Auto-select artık `gemini-2.5-flash-preview-04-17` kullanıyor (çok daha güçlü kod anlama); UI dropdown'a Gemini 2.5 Pro da eklendi
- **`AgentResult.saved_files`**: Hangi dosyaların kaydedildiği artık result modeline de yazılıyor

### v0.6.0 — 2026-04-11
- **Aria model değişikliği**: gemma3:12b → qwen2.5-coder:14b (instruction following çok daha güvenilir)
- **Supervisor plan prompt**: Tech stack kısıtlarını (HTML/CSS/JS only vb.) artık her task'ın `context` alanına yazar
- **Orchestrator constraint injection**: `_extract_constraint()` ile hedeften kısıtlar regex ile çıkarılır ve Mila planı atlasa bile tüm task'lara enjekte edilir (belt-and-suspenders)
- **MAX_CTX_CHARS**: 3000 → 6000 (Kenji, Aria'nın çıktısının daha büyük bölümünü görür)

### v0.5.0 — 2026-04-04
- **`<think>` blok filtreleme**: deepseek-r1 gibi reasoning modellerin `<think>...</think>` blokları
  artık ne terminale ne de UI'a sızmıyor — hem backend (streaming + blocking) hem frontend filtreli
- **Aria (Researcher) — Tech stack kısıtı**: Kullanıcı "HTML/CSS/JS only" gibi bir kısıt belirtirse
  Aria bunu zorunlu olarak karşılaştırır, React/Next.js/Flask önermez; her çıktıda `## Constraints Respected` bölümü eklendi
- **Kenji (Coder) — Tam uygulama zorunluluğu**: Placeholder, stub, TODO artık yasak;
  web projesinde gerçek CSS, gerçek içerik, tüm bölümler zorunlu; `[SELF-CHECK]` adımı eklendi
- **Mila (Supervisor) — Sert kalite değerlendirmesi**: Coder çıktısı skeleton ise "Kısmi" olarak
  işaretlenir, "Başarılı" değil; her eksiklik tek tek listelenir; snippet sınırı 1800 → 3500 char

### v0.4.0 — 2026-04-04
- Arayüzden canlı supervisor değiştirme (Bulut / Yerel sekmeleri)
- `/supervisor/models` endpoint: kurulu Ollama modelleri + bulut seçenekleri
- `set_supervisor` WebSocket mesajı ile anlık model değişimi
- Supervisor değişiminde header, Mila kartı ve log otomatik güncelleniyor
- Bulut sekmesinde API key uyarısı, Yerel sekmesinde Ollama durum mesajı
- ChromaDB oturum sayısı health endpoint'ine eklendi
- `requirements.txt` eksik paketler kuruldu (ollama, aiofiles, rich)

### v0.3.0 — 2026-04-04
- **Phase 6**: ChromaDB vector bellek entegrasyonu (nomic-embed-text)
- **Phase 5**: Gerçek zamanlı Web UI (FastAPI + WebSocket)
  - Dark theme, ajan kartları, plan vizualizasyonu, sistem logu
  - Token-level streaming tüm ajanlarda
- Supervisor auto-select: internet kontrolü → Gemini/Claude/Yerel
- `deepseek-r1:14b` ve `phi4:14b` offline supervisor önerileri eklendi
- Offline öncelik sırası `config.py`'de yönetilebilir

### v0.2.0 — 2026-04-04
- Tüm ajanlara persona sistemi eklendi (Mila, Aria, Kenji, Rex, Zara, Neo)
- Streaming desteği (`base_agent._generate`)
- Event sistemi (`core/events.py`)

### v0.1.0 — 2026-04-04
- İlk mimari kurulum
- Donanım analizi: RTX 4090 Laptop 16GB + Core Ultra 9 185H + 32GB RAM
- 5 uzman ajan + Supervisor
- Paralel yürütme orkestratörü

---

*Her aşama sonunda bu dosya güncellenir.*
