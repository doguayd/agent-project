from __future__ import annotations

from collections import deque
from typing import Optional

from core.models import Message


class ConversationMemory:
    """
    Her ajan için bağımsız, sınırlandırılmış konuşma hafızası.
    Global bağlam anahtar-değer deposu ile birlikte çalışır.
    """

    def __init__(self, max_messages: int = 40, agent_name: str = ""):
        self._messages: deque[Message] = deque(maxlen=max_messages)
        self._context:  dict[str, str] = {}
        self.agent_name = agent_name

    # ── Mesaj yönetimi ────────────────────────────────────────────────────

    def add(self, role: str, content: str) -> None:
        self._messages.append(
            Message(role=role, content=content, agent=self.agent_name)
        )

    def get_as_dicts(self, last_n: Optional[int] = None) -> list[dict]:
        msgs = list(self._messages)
        if last_n:
            msgs = msgs[-last_n:]
        return [{"role": m.role, "content": m.content} for m in msgs]

    def clear_messages(self) -> None:
        self._messages.clear()

    # ── Global bağlam deposu ──────────────────────────────────────────────

    def set(self, key: str, value: str) -> None:
        self._context[key] = value

    def get(self, key: str, default: str = "") -> str:
        return self._context.get(key, default)

    def delete(self, key: str) -> None:
        self._context.pop(key, None)

    def clear_all(self) -> None:
        self._messages.clear()
        self._context.clear()

    # ── Yardımcılar ───────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._messages)

    def __repr__(self) -> str:
        return (
            f"ConversationMemory(agent={self.agent_name!r}, "
            f"messages={len(self._messages)}, "
            f"context_keys={list(self._context.keys())})"
        )
