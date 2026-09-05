"""Small, atomic, backend-only session store for a single local user."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SavedSession:
    api_key: str = field(repr=False)
    access_token: str = field(repr=False)
    browser_session_hash: str = field(repr=False)
    saved_at: str

    def matches(self, browser_session: str | None) -> bool:
        if not browser_session:
            return False
        digest = hashlib.sha256(browser_session.encode()).hexdigest()
        return hmac.compare_digest(digest, self.browser_session_hash)


class SessionStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> SavedSession | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            session = SavedSession(**data)
            if not all(isinstance(value, str) and value for value in asdict(session).values()):
                return None
            datetime.fromisoformat(session.saved_at)
            return session
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(self, session: SavedSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix="session-", suffix=".tmp", dir=self.path.parent)
        try:
            # mkstemp uses owner-only permissions on POSIX. Windows inherits the
            # user's directory ACL; do not place this store in a shared folder.
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(asdict(session), output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
