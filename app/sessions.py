import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable


SESSION_COOKIE_NAME = "onboarding_session"
SESSION_TTL_SECONDS = 30 * 60
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CONTENT_CHARACTERS = 2000


@dataclass
class Session:
    role_id: str
    created_at: float
    last_seen_at: float
    history: list[dict[str, str]] = field(default_factory=list)
    active_task_id: str | None = None
    pending_update: object | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class SessionStore:
    def __init__(
        self,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        max_sessions: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(self, role_id: str) -> tuple[str, Session]:
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            if len(self._sessions) >= self.max_sessions:
                oldest_token = min(
                    self._sessions,
                    key=lambda token: self._sessions[token].last_seen_at,
                )
                del self._sessions[oldest_token]

            token = secrets.token_urlsafe(32)
            session = Session(role_id=role_id, created_at=now, last_seen_at=now)
            self._sessions[token] = session
            return token, session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None

        now = self._clock()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if now - session.last_seen_at >= self.ttl_seconds:
                del self._sessions[token]
                return None
            session.last_seen_at = now
            return session

    def delete(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def record_exchange(self, session: Session, user_message: str, assistant_message: str) -> None:
        with session.lock:
            session.history.extend(
                [
                    {"role": "user", "content": user_message[:MAX_HISTORY_CONTENT_CHARACTERS]},
                    {"role": "assistant", "content": assistant_message[:MAX_HISTORY_CONTENT_CHARACTERS]},
                ]
            )
            del session.history[:-MAX_HISTORY_MESSAGES]

    def _remove_expired(self, now: float) -> None:
        expired_tokens = [
            token
            for token, session in self._sessions.items()
            if now - session.last_seen_at >= self.ttl_seconds
        ]
        for token in expired_tokens:
            del self._sessions[token]