"""Security building blocks shared by the API, the agent and the model client.

- EventLog: an append-only, hash-chained log of security events (sign-ins, refusals,
  lockouts, escalations, decisions, prompt-injection flags). Each entry carries the hash
  of the one before, so editing or deleting a line breaks the chain and shows.
- RateLimiter: a sliding-window limit per key (an IP address, a user).
- CircuitBreaker: stops calling the language model after repeated failures, so the
  deterministic fallbacks take over at once instead of each request waiting to fail.
- Validators and HTTP security headers.
"""

import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

CLIENT_ID = re.compile(r"^(MWILA|ZM)-\d{3,4}$")


def valid_client_id(cid: str) -> bool:
    """Client ids are built into file paths: only this exact shape is ever accepted."""
    return bool(CLIENT_ID.match(cid or ""))


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, text: str) -> None:
    """Write to a temp file and swap it in, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)


class EventLog:
    GENESIS = "0" * 64

    def __init__(self, path: str | Path = "data/security/events.jsonl"):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return self.GENESIS
        lines = self.path.read_text("utf-8").strip().splitlines()
        return json.loads(lines[-1])["hash"] if lines else self.GENESIS

    @staticmethod
    def _digest(entry: dict) -> str:
        body = {k: v for k, v in entry.items() if k != "hash"}
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    def record(self, event: str, *, user: str | None = None, ip: str | None = None,
               severity: str = "info", **details) -> dict:
        with self.lock:
            entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "event": event, "severity": severity, "user": user, "ip": ip,
                     "details": details, "prev": self._last_hash()}
            entry["hash"] = self._digest(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            return entry

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text("utf-8").splitlines() if line]

    def verify(self) -> dict:
        """Walk the chain; report the first line that was edited, removed or reordered."""
        prev = self.GENESIS
        entries = self.entries()
        for i, e in enumerate(entries):
            if e.get("prev") != prev or self._digest(e) != e.get("hash"):
                return {"intact": False, "entries": len(entries), "broken_at": i + 1}
            prev = e["hash"]
        return {"intact": True, "entries": len(entries), "broken_at": None}


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


class CircuitBreaker:
    """Closed: calls go through. Open: calls are skipped until the cool-down ends."""

    def __init__(self, failures: int = 3, window_s: float = 300, cooldown_s: float = 300):
        self.failures, self.window_s, self.cooldown_s = failures, window_s, cooldown_s
        self.recent = deque()
        self.open_until = 0.0
        self.trips = 0
        self.last_error = None
        self.lock = threading.Lock()

    def is_open(self) -> bool:
        return time.monotonic() < self.open_until

    def failure(self, error: str) -> bool:
        """Record a failure; True if this one opened the circuit."""
        now = time.monotonic()
        with self.lock:
            self.last_error = error[:200]
            self.recent.append(now)
            while self.recent and now - self.recent[0] > self.window_s:
                self.recent.popleft()
            if len(self.recent) >= self.failures and not self.is_open():
                self.open_until = now + self.cooldown_s
                self.trips += 1
                self.recent.clear()
                return True
        return False

    def success(self) -> None:
        with self.lock:
            self.recent.clear()

    def state(self) -> dict:
        remaining = max(0.0, self.open_until - time.monotonic())
        return {"state": "open" if remaining else "closed", "reopens_in_s": round(remaining),
                "trips": self.trips, "last_error": self.last_error}


class TokenBudget:
    """A daily cap on language-model tokens, so a busy or abusive day can't run up cost."""

    def __init__(self, daily: int):
        self.daily, self.day, self.used = daily, None, 0
        self.lock = threading.Lock()

    def _roll(self):
        today = datetime.now(timezone.utc).date()
        if self.day != today:
            self.day, self.used = today, 0

    def exhausted(self) -> bool:
        with self.lock:
            self._roll()
            return self.used >= self.daily

    def spend(self, tokens: int) -> None:
        with self.lock:
            self._roll()
            self.used += tokens

    def state(self) -> dict:
        with self.lock:
            self._roll()
            return {"daily_limit": self.daily, "used_today": self.used}


# Shared by the model client (labelling, memo, agent) and reported by /api/health.
MODEL_BREAKER = CircuitBreaker()
MODEL_BUDGET = TokenBudget(int(os.environ.get("INSAKA_DAILY_TOKEN_BUDGET", "150000")))

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
