"""
Vector Bellek (ChromaDB + nomic-embed-text)
===========================================
Tamamlanan oturumları kalıcı olarak saklar.
Yeni görevlerde benzer geçmiş bağlamı otomatik çeker.

Embedding: nomic-embed-text (Ollama üzerinden — zaten kurulu)
Depolama:  ChromaDB (yerel, persist)

Not: Embedding'ler Ollama üzerinden manuel hesaplanıp ChromaDB'ye
     doğrudan verilir — EmbeddingFunction Protocol sorunu olmaz.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

_ZERO_VEC_DIM = 768  # nomic-embed-text vektör boyutu


class VectorMemory:
    """
    Geçmiş oturumları sakla ve geri çağır.

    Kullanım:
        vm = VectorMemory()
        ctx  = await vm.recall("Flask API yaz")       # benzer geçmiş
        await vm.save("sess_01", "Flask API yaz", review)
    """

    # Hata mesajını yalnızca bir kez göster (process başına)
    _warned: bool = False

    def __init__(
        self,
        persist_path: str = "./chroma_db",
        ollama_host: str  = "http://localhost:11434",
    ) -> None:
        self._path        = persist_path
        self._ollama_host = ollama_host
        self._col         = None    # lazy init
        self._unavailable = False   # chromadb yüklü değilse tekrar deneme

    # ── Embedding ─────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Ollama üzerinden sync embedding hesapla."""
        try:
            import ollama
            client = ollama.Client(host=self._ollama_host)
            resp   = client.embeddings(model="nomic-embed-text", prompt=text[:512])
            return list(resp.embedding)
        except Exception:
            return [0.0] * _ZERO_VEC_DIM

    # ── İç başlatma ───────────────────────────────────────────────────────

    def _init(self) -> bool:
        if self._col is not None:
            return True
        if self._unavailable:
            return False
        try:
            import chromadb

            Path(self._path).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=self._path)

            # Embedding function KULLANMIYORUZ — embeddings doğrudan verilir.
            # Bu sayede chromadb'nin EmbeddingFunction Protocol'u devre dışı.
            self._col = client.get_or_create_collection(
                name     = "agent_sessions",
                metadata = {"hnsw:space": "cosine"},
            )
            return True

        except ImportError:
            if not VectorMemory._warned:
                VectorMemory._warned = True
                print(
                    "[VectorMemory] chromadb kurulu değil — kalıcı bellek devre dışı.\n"
                    "  Kurmak için: pip install chromadb"
                )
            self._unavailable = True
            return False

        except Exception as exc:
            if not VectorMemory._warned:
                VectorMemory._warned = True
                print(f"[VectorMemory] Başlatma başarısız: {exc}")
            self._unavailable = True
            return False

    # ── Public API ────────────────────────────────────────────────────────

    async def recall(self, goal: str, n: int = 3) -> str:
        """
        Benzer geçmiş oturumları çek.
        Returns: Researcher'a enjekte edilecek bağlam string'i (boş olabilir).
        """
        try:
            ok = await asyncio.to_thread(self._init)
            if not ok or self._col is None:
                return ""

            count = await asyncio.to_thread(self._col.count)
            if count == 0:
                return ""

            # Sorgu embedding'ini manuel hesapla
            query_emb = await asyncio.to_thread(self._embed, goal)

            results = await asyncio.to_thread(
                self._col.query,
                query_embeddings = [query_emb],
                n_results        = min(n, count),
                include          = ["documents", "metadatas"],
            )

            docs  = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]

            if not docs:
                return ""

            parts = []
            for doc, meta in zip(docs, metas):
                goal_label = meta.get("goal", "")[:80]
                parts.append(f"[Geçmiş: {goal_label}]\n{doc[:600]}")

            return "📚 BENZER GEÇMİŞ GÖREVLER:\n" + "\n\n".join(parts)

        except Exception as exc:
            print(f"[VectorMemory] recall hatası: {exc}")
            return ""

    async def save(self, session_id: str, goal: str, final_review: str) -> None:
        """Oturum sonucunu kaydet."""
        try:
            ok = await asyncio.to_thread(self._init)
            if not ok or self._col is None:
                return

            document = f"Hedef: {goal}\n\nSonuç Özeti:\n{final_review[:1800]}"

            # Embedding'i manuel hesapla
            emb = await asyncio.to_thread(self._embed, document[:512])

            await asyncio.to_thread(
                self._col.upsert,
                ids        = [session_id],
                documents  = [document],
                embeddings = [emb],
                metadatas  = [{"goal": goal[:200], "session_id": session_id}],
            )
        except Exception as exc:
            print(f"[VectorMemory] save hatası: {exc}")

    async def count(self) -> int:
        try:
            ok = await asyncio.to_thread(self._init)
            if not ok:
                return 0
            return await asyncio.to_thread(self._col.count)
        except Exception:
            return 0
