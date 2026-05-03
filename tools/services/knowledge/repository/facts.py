import sqlite3
import datetime
from typing import List, Dict, Optional

class FactRepository:
    """Handles structured facts (entities, categories, sources)."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path

    def add(self, fact: str, entity: str = None, category: str = "general", 
            source: str = "assistant", confidence: str = "high"):
        now = datetime.datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO facts (fact, entity, category, source, confidence, created_at, updated_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (fact, entity, category, source, confidence, now, now)
            )
            return cursor.lastrowid

    def list(self, query: str = None, category: str = None) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = "SELECT * FROM facts WHERE 1=1"
            params = []
            if query:
                sql += " AND fact LIKE ?"
                params.append(f"%{query}%")
            if category:
                sql += " AND category = ?"
                params.append(category)
            
            cursor.execute(sql + " ORDER BY created_at DESC", params)
            return [dict(row) for row in cursor.fetchall()]
