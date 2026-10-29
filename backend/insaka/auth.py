"""Staff sign-in with multi-factor authentication.

    password  ->  short-lived MFA ticket  ->  6-digit authenticator code  ->  access token

- Passwords are checked against scrypt hashes; the demo password comes from
  INSAKA_DEMO_PASSWORD and is never in the repository.
- Each account's TOTP secret is derived from INSAKA_SECRET_KEY, so it survives restarts
  without being stored anywhere. Codes are standard RFC 6238 (Google or Microsoft
  Authenticator), accepted one step either side, and never twice (replay protection).
- Five wrong passwords or codes lock the account for 15 minutes.
- Access tokens are signed, last 30 minutes and carry a session id that sign-out revokes.
- INSAKA_DEMO_MFA_HELPER=1 (prototype only) returns the current code with the MFA ticket,
  so judges can sign in without an authenticator app. It is reported on the Security screen.
"""

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time

import pyotp
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .case import USERS

ACCESS_TTL_S = 30 * 60
MFA_TTL_S = 5 * 60
UPLOAD_TTL_S = 7 * 24 * 3600
LOCK_AFTER = 5
LOCK_FOR_S = 15 * 60
ISSUER = "Insaka (Absa prototype)"

DEV_SECRET = "insaka-local-development-only"
DEV_PASSWORD = "insaka-local-demo"


def production() -> bool:
    return os.environ.get("INSAKA_ENV") == "production"


# In production a missing secret is never replaced by the published development default:
# a random one is used instead, so nobody can sign in until it is configured.
_RANDOM_SECRET = secrets.token_urlsafe(32)


def secret_key() -> str:
    return os.environ.get("INSAKA_SECRET_KEY") or (_RANDOM_SECRET if production() else DEV_SECRET)


def using_dev_secrets() -> dict:
    return {"secret_key": not os.environ.get("INSAKA_SECRET_KEY"),
            "password": not os.environ.get("INSAKA_DEMO_PASSWORD")}


def demo_helper_on() -> bool:
    return os.environ.get("INSAKA_DEMO_MFA_HELPER") == "1"


def _serializer(purpose: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key(), salt=f"insaka-{purpose}")


def totp_secret(username: str) -> str:
    raw = hmac.new(secret_key().encode(), f"totp:{username}".encode(), hashlib.sha256).digest()
    return base64.b32encode(raw[:20]).decode().rstrip("=")


def totp(username: str) -> pyotp.TOTP:
    return pyotp.TOTP(totp_secret(username), issuer=ISSUER, name=username)


# --- customer upload links ------------------------------------------------------------

def upload_token(client_id: str) -> str:
    """A signed link token bound to one application, valid for seven days."""
    return _serializer("upload").dumps({"c": client_id})


def client_for_upload_token(token: str) -> str | None:
    try:
        return _serializer("upload").loads(token, max_age=UPLOAD_TTL_S)["c"]
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None


class AuthError(Exception):
    """Sign-in failed. The message is deliberately the same whatever was wrong."""


class Authenticator:
    def __init__(self):
        password = os.environ.get("INSAKA_DEMO_PASSWORD") or (
            secrets.token_urlsafe(24) if production() else DEV_PASSWORD)
        self.hashes = {u: generate_password_hash(password, method="scrypt") for u in USERS}
        self.failures = {}          # username -> [count, first_at]
        self.locked_until = {}      # username -> time
        self.last_step = {}         # username -> last accepted TOTP time step
        self.revoked = set()        # session ids signed out
        self.lock = threading.Lock()

    # --- lockout -------------------------------------------------------------------
    def locked(self, username: str) -> bool:
        return time.time() < self.locked_until.get(username, 0)

    def _fail(self, username: str) -> bool:
        """Count a failure; True if the account is now locked."""
        with self.lock:
            count, first = self.failures.get(username, [0, time.time()])
            if time.time() - first > LOCK_FOR_S:
                count, first = 0, time.time()
            count += 1
            self.failures[username] = [count, first]
            if count >= LOCK_AFTER:
                self.locked_until[username] = time.time() + LOCK_FOR_S
                self.failures.pop(username, None)
                return True
        return False

    def _ok(self, username: str) -> None:
        with self.lock:
            self.failures.pop(username, None)

    # --- step 1: password ----------------------------------------------------------
    def check_password(self, username: str, password: str) -> dict:
        if username in USERS and self.locked(username):
            raise AuthError("locked")
        valid = username in self.hashes and check_password_hash(self.hashes[username], password or "")
        if not valid:
            if username in USERS and self._fail(username):
                raise AuthError("locked_now")
            raise AuthError("invalid")
        ticket = _serializer("mfa").dumps({"u": username, "n": secrets.token_hex(8)})
        out = {"mfa_ticket": ticket, "expires_in": MFA_TTL_S}
        if demo_helper_on():
            out["demo_code"] = totp(username).now()
        return out

    def ticket_user(self, ticket: str) -> str:
        try:
            return _serializer("mfa").loads(ticket, max_age=MFA_TTL_S)["u"]
        except (BadSignature, SignatureExpired, KeyError, TypeError):
            raise AuthError("ticket")

    def enrolment(self, ticket: str) -> dict:
        username = self.ticket_user(ticket)
        t = totp(username)
        return {"username": username, "secret": t.secret,
                "uri": t.provisioning_uri(name=username, issuer_name=ISSUER)}

    # --- step 2: authenticator code ------------------------------------------------
    def check_code(self, ticket: str, code: str) -> dict:
        username = self.ticket_user(ticket)
        if self.locked(username):
            raise AuthError("locked")
        code = (code or "").replace(" ", "")
        t = totp(username)
        now = int(time.time())
        step = None
        if code.isdigit() and len(code) == 6:
            for offset in (-1, 0, 1):
                at = now + offset * t.interval
                if hmac.compare_digest(t.at(at), code):
                    step = at // t.interval
                    break
        if step is None:
            if self._fail(username):
                raise AuthError("locked_now")
            raise AuthError("code")
        with self.lock:
            if step <= self.last_step.get(username, -1):
                raise AuthError("replay")
            self.last_step[username] = step
        self._ok(username)
        return self.issue(username)

    # --- tokens --------------------------------------------------------------------
    def issue(self, username: str) -> dict:
        sid = secrets.token_hex(12)
        token = _serializer("access").dumps({"u": username, "sid": sid})
        return {"access_token": token, "expires_in": ACCESS_TTL_S,
                "user": {"id": username, **USERS[username]}}

    def verify(self, token: str) -> tuple[str, str]:
        """(username, session id) for a valid, unexpired, unrevoked token."""
        try:
            data = _serializer("access").loads(token, max_age=ACCESS_TTL_S)
        except SignatureExpired:
            raise AuthError("expired")
        except (BadSignature, TypeError):
            raise AuthError("invalid_token")
        if data.get("sid") in self.revoked or data.get("u") not in USERS:
            raise AuthError("revoked")
        return data["u"], data["sid"]

    def revoke(self, sid: str) -> None:
        self.revoked.add(sid)
