from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChatSession:
    session_id: str
    filename: str
    dataframe: Any
    source_dataframe: Any
    agent: Any
    upload_path: str
    created_at: datetime = field(default_factory=utc_now)
    last_accessed_at: datetime = field(default_factory=utc_now)


class SessionStore:
    """Thread-safe in-memory store for active development sessions.

    Replace this with Redis/database storage when deploying multiple workers.
    The PandasAI agent itself remains process-local because it holds conversation
    state and the loaded DataFrame.
    """

    def __init__(self, ttl_minutes: int = 60, max_sessions: int = 20) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = RLock()
        self._ttl = timedelta(minutes=max(1, ttl_minutes))
        self._max_sessions = max(1, max_sessions)

    def _remove_expired(self) -> None:
        cutoff = utc_now() - self._ttl
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.last_accessed_at < cutoff
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def create(self, session: ChatSession) -> None:
        with self._lock:
            self._remove_expired()
            if len(self._sessions) >= self._max_sessions:
                raise ValueError("The server is at its active dataset limit. Delete an unused dataset and retry.")
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> ChatSession | None:
        with self._lock:
            self._remove_expired()
            session = self._sessions.get(session_id)
            if session:
                session.last_accessed_at = utc_now()
            return session

    def delete(self, session_id: str) -> ChatSession | None:
        with self._lock:
            return self._sessions.pop(session_id, None)

    def count(self) -> int:
        with self._lock:
            self._remove_expired()
            return len(self._sessions)

