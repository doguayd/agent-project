# Master MCP Server - Kişisel Gelişim Yol Haritası

Bu döküman, projenin senin kişisel ihtiyaçlarına göre nasıl şekilleneceğini özetler.

## 📅 Mevcut Durum (Faz 1 & Zekâ Katmanı Tamamlandı ✅)

- Ollama asenkron entegrasyonu.
- Güvenli dosya sistemi ve merkezi loglama.
- **Zekâ Katmanı**: Planlayıcı, Optimizer, Critic, Syntax Guardian ve Sequential Thinking araçları aktif.
- **Tool Envanteri**: Araçların işlev ve maliyetlerini raporlayan katalog sistemi.

---

## 🚀 Faz 2: Gelişmiş Bilgi ve Hafıza (The "Brain") - Tamamlandı ✅

### 1. Web Arama (Tamamlandı ✅)

- `ddgs` entegrasyonu ile asenkron bilgi çekme.

### 2. Tamamen Yerel ve Çok Dilli Hafıza (Tamamlandı ✅)

- **Teknoloji**: `llama-cpp-python` + `paraphrase-multilingual` (L12) + `SQLite`.
- **Başarı**: Ollama'dan bağımsız, Türkçe destekli anlamsal arama ve RAG altyapısı kuruldu.
- **Normalizasyon**: Proje bazlı veritabanı yolları sabitlendi ve stabilize edildi.

### 3. Kişisel Olgu Hafızası (Long-term Facts)

- **Durum**: Temel KV (Key-Value) yapısı kuruldu, kişisel alışkanlıklar ve tercihler global hafızada saklanabiliyor.

---

## 🛠️ Faz 4: Şeffaflık ve Optimizasyon (The "Visibility" Phase) - Tamamlandı ✅

### 1. Okunabilir Proje Kimlikleri (Readable Project IDs)

- **Hedef**: `proje-hash` formatından, tam dosya yolunun düzleştirilmiş haline (`c--Users-akbas...`) geçiş yapmak.
- **Amaç**: `.mcp-master/projects` klasöründeki verilerin hangi projeye ait olduğunun kullanıcı tarafından kolayca anlaşılabilmesi.

### 2. İnsan Tarafından Okunabilir Hafıza (MEMORY.md Sync)

- **Hedef**: Önemli olgu ve tercihlerin (Facts), SQLite veritabanına ek olarak projenin hafıza klasöründe bir `MEMORY.md` dosyasına otomatik olarak "aynalanması" (Mirroring).
- **Amaç**: Claude'daki hafıza yapısına benzer şekilde, AI'ın neyi hatırladığını şeffaf bir şekilde görmek ve gerekirse dosya üzerinden manuel müdahale edebilmek.
- **Kritik Not**: `MEMORY.md` dosyasının aşırı şişmemesi (bloating) sağlanmalıdır. SQLite veritabanına kaydedilen her düşük seviyeli teknik veri buraya yansıtılmamalıdır; sadece işlevsel ve önemli "olgu ve tercihler" (high-level facts) tutulmalıdır, aksi takdirde hafıza işlevselliğini yitirir.

### 3. Model Performans Optimizasyonu (ask_expert)

- **Not**: Yerel model zaten küçük olduğundan, performans sorunu sadece model boyutuyla ilgili değildir.
- **Hedef**: `ask_expert` aracının cevap hızını ve verimliliğini artırmak için girdi (input) boyutu, çıktı (output) limitleri ve sistem prompt (prompts) yapısını dengelemek (balanslamak).

---

## 🎯 Faz 5: Yeni MCP Araçları (Current Priority)

Bu faza, AI asistanın geliştirme iş akışında **gerçekten eksik olan** 5 pratik MCP aracı planlanmıştır.
Her biri mevcut mimariye minimum değişiklikle entegre edilebilir.

### 1. 🐍 **Code Execution Sandbox** (Faz 5.1)

**Neden Gerekli**: AI kod yazıp dosyaya kaydedebiliyor ama çalıştıramıyor. Snippet test etmek, küçük hesaplama yapmak için her seferinde kullanıcının terminale geçmesi gerekiyor.

**Yapılacaklar**:
- Python snippet'larını güvenli subprocess ile çalıştır, stdout/stderr döndür
- Zaman aşımı (default: 10s) ile sonsuz döngü koruması
- Çalışma dizini proje root'una kilitli

**Etkilenen Dosyalar**:
- Yeni: `services/core/execution_service.py`
- Yeni tool: `run_python` (`tools/file_ops.py`'ye eklenir)

---

### 2. 🌐 **Local HTTP Client** (Faz 5.2)

**Neden Gerekli**: Geliştirirken `localhost:8000` gibi local API'leri test etmek çok yaygın. AI şu an bu istekleri atamıyor.

**Yapılacaklar**:
- GET / POST / PUT / DELETE desteği
- JSON body, custom headers, query params
- Response body + status code + latency döndür
- Sadece `localhost` ve private IP'lere izin (güvenlik)

**Etkilenen Dosyalar**:
- Yeni: `services/knowledge/http_client_service.py`
- Yeni tool: `http_request` (`tools/research.py`'ye eklenir)
- Yeni bağımlılık: `httpx` (async HTTP)

---

### 3. 📄 **Diff & Patch Tool** (Faz 5.3)

**Neden Gerekli**: `git_diff` var ama git dışı iki dosyayı/string'i karşılaştırmak ve patch uygulamak için araç yok. Refactoring sırasında AI'ın değişiklikleri doğrulaması gerekiyor.

**Yapılacaklar**:
- İki dosya veya string arası unified diff üret
- Unified diff patch dosyasını bir hedefe uygula
- Ek bağımlılık yok (`difflib` stdlib'de mevcut)

**Etkilenen Dosyalar**:
- `services/core/file_service.py`'ye metod eklenir
- Yeni tools: `diff_files`, `apply_patch` (`tools/file_ops.py`'ye eklenir)

---

### 4. 🔑 **Env File Manager** (Faz 5.4)

**Neden Gerekli**: `.env` dosyaları her projede var. AI bunları parse edip okuyamıyor, yeni key ekleyemıyor. Direkt `read_file` ile hassas değerler sızabilir.

**Yapılacaklar**:
- `.env` dosyasını parse et, key listesi döndür
- Değer maskeleme: `SECRET`, `TOKEN`, `PASSWORD`, `KEY` içeren değerleri `***` göster
- Yeni key ekle / var olanı güncelle
- Ek bağımlılık yok (stdlib ile parse edilir)

**Etkilenen Dosyalar**:
- Yeni tools: `read_env_file`, `write_env_key` (`tools/file_ops.py`'ye eklenir)

---

### 5. 🔍 **Process & Port Inspector** (Faz 5.5)

**Neden Gerekli**: "Ollama çalışıyor mu?", "8000 portu dolu mu?" gibi sorular sık sorulur. Şu an AI bunlara cevap veremiyor.

**Yapılacaklar**:
- Belirli bir port'un kullanımda olup olmadığını kontrol et
- Process adıyla PID ve durum bul (örn. `ollama`, `python`, `node`)
- Cross-platform: Windows + Linux/Mac

**Etkilenen Dosyalar**:
- `services/core/diagnostic_service.py`'ye metod eklenir
- Yeni tools: `check_port`, `find_process` (`tools/diagnostics.py`'ye eklenir)
- Yeni bağımlılık: `psutil`

---

## 📋 Uygulama Sırası & Success Criteria

| # | Özellik | Yeni Bağımlılık | Etkilenen Modüller | Durum |
|---|---------|-----------------|-------------------|-------|
| 1 | Code Execution | Yok (stdlib) | `execution_service`, `file_ops` | 📋 Planlandı |
| 2 | HTTP Client | `httpx` | `http_client_service`, `research` | 📋 Planlandı |
| 3 | Diff & Patch | Yok (difflib) | `file_service`, `file_ops` | 📋 Planlandı |
| 4 | Env Manager | Yok (stdlib) | `file_ops` | 📋 Planlandı |
| 5 | Process Inspector | `psutil` | `diagnostic_service`, `diagnostics` | 📋 Planlandı |

**Her özellik tamamlandığında**:
- ✅ `smoke_test.py` başarıyla çalışmalı
- ✅ Graceful degradation (eksik bağımlılıkta crash yok)
- ✅ Audit logging entegre
- ✅ Unit test coverage >80%
