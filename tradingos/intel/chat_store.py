"""Persistence for AI Research Chat conversations (chat_messages table)."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, func, select

from tradingos.db.models import ChatMessage
from tradingos.db.session import session_scope

MAX_TEXT = 60_000


def new_conversation() -> str:
    return uuid.uuid4().hex[:16]


def add(conversation: str, role: str, text: str, model: str = "", sources: list[dict] | None = None) -> None:
    if role not in ("user", "assistant", "error"):
        raise ValueError(f"invalid role {role!r}")
    with session_scope() as s:
        s.add(ChatMessage(conversation=conversation, role=role, text=(text or "")[:MAX_TEXT], model=model[:64],
                          sources_json=json.dumps(sources or [])[:200_000]))


def history(conversation: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(ChatMessage).where(ChatMessage.conversation == conversation)
                         .order_by(ChatMessage.id)).all()
        return [{"role": r.role, "text": r.text, "model": r.model, "created_at": r.created_at,
                 "sources": json.loads(r.sources_json or "[]")} for r in rows]


def conversations(limit: int = 30) -> list[dict]:
    """Most recent conversations with their first question as a title."""
    with session_scope() as s:
        last = (select(ChatMessage.conversation, func.max(ChatMessage.created_at).label("last"),
                       func.count(ChatMessage.id).label("n"))
                .group_by(ChatMessage.conversation).order_by(func.max(ChatMessage.created_at).desc()).limit(limit))
        out = []
        for conv, ts, n in s.execute(last).all():
            first = s.scalars(select(ChatMessage.text).where(ChatMessage.conversation == conv,
                                                              ChatMessage.role == "user")
                              .order_by(ChatMessage.id).limit(1)).first()
            out.append({"conversation": conv, "last": ts, "messages": n, "title": (first or "(empty)")[:80]})
        return out


def delete_conversation(conversation: str) -> int:
    with session_scope() as s:
        return s.execute(delete(ChatMessage).where(ChatMessage.conversation == conversation)).rowcount or 0
