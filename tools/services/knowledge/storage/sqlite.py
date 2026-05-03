import sqlite3
import json
import numpy as np
from typing import List, Dict, Any, Optional

class SQLiteStore:
    """Lite storage for vectors and structured data."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id TEXT PRIMARY KEY, content TEXT NOT NULL, 
                    metadata TEXT, embedding BLOB, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT NOT NULL,
                    entity TEXT, category TEXT, source TEXT, confidence TEXT,
                    created_at DATETIME, updated_at DATETIME
                )
            """)
            conn.commit()

    def add_vector(self, doc_id: str, content: str, metadata: Dict[str, Any], embedding: List[float]):
        embedding_blob = np.array(embedding, dtype=np.float32).tobytes()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO knowledge (id, content, metadata, embedding) VALUES (?, ?, ?, ?)",
                (doc_id, content, json.dumps(metadata), embedding_blob)
            )
            conn.commit()

    def delete_vector_by_id(self, doc_id: str):
        """Removes a document from the vector store."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM knowledge WHERE id = ?", (doc_id,))
            conn.commit()

    def get_all_ids(self) -> List[str]:
        """Returns all document IDs (paths) in the knowledge store."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM knowledge")
            return [row[0] for row in cursor.fetchall()]

    def query_vector(self, query_vec: List[float], n: int = 5) -> List[Dict]:
        query_np = np.array(query_vec, dtype=np.float32)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, content, metadata, embedding FROM knowledge")
            rows = cursor.fetchall()
        
        results = []
        for doc_id, content, meta, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            similarity = np.dot(query_np, vec) / (np.linalg.norm(query_np) * np.linalg.norm(vec))
            results.append({"id": doc_id, "content": content, "metadata": json.loads(meta), "score": float(similarity)})
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:n]
