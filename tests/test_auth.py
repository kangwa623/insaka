import time

import pyotp
import pytest

from insaka.api import create_app
from insaka.auth import totp_secret

PASSWORD = "test-password"


@pytest.fixture()
def app(tmp_path):
    return create_app(security_dir=tmp_path / "security")


def login(c, user="rm.chanda", password=PASSWORD):
    return c.post("/api/auth/login", json={"username": user, "password": password})


def code(user="rm.chanda", at=None):
    return pyotp.TOTP(totp_secret(user)).at(at or time.time())


def test_password_then_authenticator_code_then_token(app):
    c = app.test_client()
    r = login(c)
    assert r.status_code == 200 and "mfa_ticket" in r.json and "demo_code" not in r.json
    ticket = r.json["mfa_ticket"]
    r = c.post("/api/auth/mfa", json={"mfa_ticket": ticket, "code": code()})
    assert r.status_code == 200 and r.json["user"]["id"] == "rm.chanda"
    token = r.json["access_token"]
    me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json["id"] == "rm.chanda"
    # The password alone is never enough: the ticket is not an access token.
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401


def test_wrong_password_unknown_user_and_wrong_code_look_the_same(app):
    c = app.test_client()
    a = login(c, password="nope")
    b = login(c, user="nobody")
    assert a.status_code == b.status_code == 401 and a.json == b.json
    ticket = login(c).json["mfa_ticket"]
    assert c.post("/api/auth/mfa", json={"mfa_ticket": ticket, "code": "000000"}).status_code == 401


def test_code_cannot_be_replayed(app):
    c = app.test_client()
    now = code()
    t1 = login(c).json["mfa_ticket"]
    assert c.post("/api/auth/mfa", json={"mfa_ticket": t1, "code": now}).status_code == 200
    t2 = login(c).json["mfa_ticket"]
    r = c.post("/api/auth/mfa", json={"mfa_ticket": t2, "code": now})
    assert r.status_code == 401 and "already been used" in r.json["error"]


def test_lockout_after_five_failures(app):
    c = app.test_client()
    for _ in range(4):
        assert login(c, password="wrong").status_code == 401
    assert login(c, password="wrong").status_code == 423
    assert login(c).status_code == 423          # even the right password, while locked
    log = c.application.extensions["insaka"]["events"].entries()
    assert any(e["event"] == "account_locked" for e in log)


def test_tokens_expire_revoke_and_cannot_be_forged(app, monkeypatch):
    c = app.test_client()
    auth = app.extensions["insaka"]["auth"]
    token = auth.issue("approver.banda")["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert c.get("/api/cases", headers=h).status_code == 200
    assert c.get("/api/cases", headers={"X-User": "approver.banda"}).status_code == 401  # old header
    assert c.get("/api/cases", headers={"Authorization": f"Bearer {token[:-2]}xx"}).status_code == 401
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.get("/api/cases", headers=h).status_code == 401
    import insaka.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ACCESS_TTL_S", -1)
    fresh = auth.issue("approver.banda")["access_token"]
    assert c.get("/api/cases", headers={"Authorization": f"Bearer {fresh}"}).status_code == 401


def test_enrolment_qr_and_demo_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("INSAKA_DEMO_MFA_HELPER", "1")
    c = create_app(security_dir=tmp_path).test_client()
    r = login(c, "auditor.phiri")
    assert r.json["demo_code"] == code("auditor.phiri")
    e = c.post("/api/auth/enroll", json={"mfa_ticket": r.json["mfa_ticket"]}).json
    assert e["uri"].startswith("otpauth://totp/") and e["qr"].startswith("data:image/svg+xml")


def test_production_never_falls_back_to_the_published_dev_password(tmp_path, monkeypatch):
    from insaka.auth import DEV_PASSWORD
    monkeypatch.setenv("INSAKA_ENV", "production")
    monkeypatch.delenv("INSAKA_DEMO_PASSWORD")
    c = create_app(security_dir=tmp_path).test_client()
    assert login(c, password=DEV_PASSWORD).status_code == 401


def test_demo_signin_needs_no_password_but_still_needs_the_code(tmp_path, monkeypatch):
    monkeypatch.setenv("INSAKA_DEMO_SIGNIN", "1")
    c = create_app(security_dir=tmp_path).test_client()
    assert c.get("/api/auth/methods").json["password_required"] is False
    assert login(c, user="nobody", password="").status_code == 401
    r = login(c, password="")
    assert r.status_code == 200 and r.json["demo_code"] == code()
    ticket = r.json["mfa_ticket"]
    assert c.post("/api/auth/mfa", json={"mfa_ticket": ticket, "code": "000000"}).status_code == 401
    assert c.post("/api/auth/mfa", json={"mfa_ticket": ticket, "code": r.json["demo_code"]}).status_code == 200
    # Signing straight back in gets a fresh code, not a replay error.
    again = login(c, password="").json
    assert c.post("/api/auth/mfa", json={"mfa_ticket": again["mfa_ticket"],
                                         "code": again["demo_code"]}).status_code == 200


def test_login_is_rate_limited_per_address(app):
    c = app.test_client()
    statuses = [login(c, user=f"x{i}", password="x").status_code for i in range(12)]
    assert 429 in statuses
