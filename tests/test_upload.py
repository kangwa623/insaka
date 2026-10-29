import io
import json

import pytest

from insaka.agent import NoChat, build_case
from insaka.api import create_app
from insaka.auth import upload_token
from insaka.generator import MWILA_ID, generate

from conftest import auth_headers


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    out = tmp_path_factory.mktemp("upload")
    generate(4, 42, out, pdfs=True)
    app = create_app(out, out / "cases", out / "agent", uploads_dir=out / "uploads",
                     security_dir=out / "security", label_method="rules", memo_chat=NoChat(),
                     registry={})
    clients = {c["client_id"]: c for c in json.loads((out / "clients.json").read_text("utf-8"))}
    return out, app.test_client(), clients


def pdf(out, cid, ch):
    return (out / "statements" / f"{cid}_{ch}.pdf").read_bytes()


CONSENT = {"share": "true", "retention": "true", "dpa": "true"}


def test_customer_link_consent_and_checks(env):
    out, c, clients = env
    token = upload_token(MWILA_ID)
    assert c.get("/api/upload/not-a-token").status_code == 404
    info = c.get(f"/api/upload/{token}").json
    assert [r["channel"] for r in info["requested"]] == ["mtn"] and info["consent"] is None

    r = c.post(f"/api/upload/{token}", data={"mtn": (io.BytesIO(pdf(out, MWILA_ID, "mtn")), "s.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 400 and "consent" in r.json["error"]

    other = next(cid for cid, k in clients.items() if cid != MWILA_ID and "mtn" in k["channels"])
    r = c.post(f"/api/upload/{token}", data={**CONSENT, "mtn": (io.BytesIO(pdf(out, other, "mtn")), "s.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 400 and "not the account on the application" in r.json["error"]

    r = c.post(f"/api/upload/{token}", data={**CONSENT, "mtn": (io.BytesIO(b"not a pdf"), "s.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 400

    r = c.post(f"/api/upload/{token}", data={**CONSENT, "mtn": (io.BytesIO(pdf(out, MWILA_ID, "mtn")), "s.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 200 and r.json["uploaded"] == ["mtn"]
    assert (out / "uploads" / f"{MWILA_ID}_mtn.pdf").exists()
    docs = c.get(f"/api/cases/{MWILA_ID}/documents", headers=auth_headers(c.application, "rm.chanda")).json
    assert docs["consent"] and {s["channel"]: s["source"] for s in docs["statements"]} == \
        {"absa": "absa_internal", "mtn": "uploaded"}

    case = build_case(MWILA_ID, out, uploads_dir=out / "uploads", label_method="rules", memo_chat=NoChat())
    statement = case.sources["mtn"]()
    assert statement.account == clients[MWILA_ID]["channels"]["mtn"] and statement.rows


def test_rm_upload_is_role_checked_and_audited(env):
    out, c, _ = env
    h = auth_headers(c.application, "rm.chanda")
    assert c.post(f"/api/cases/{MWILA_ID}/run", headers=h, json={"mode": "rules"}).status_code == 200
    data = {"channel": "absa", "file": (io.BytesIO(pdf(out, MWILA_ID, "absa")), "a.pdf")}
    r = c.post(f"/api/cases/{MWILA_ID}/upload", headers=auth_headers(c.application, "approver.banda"), data=data,
               content_type="multipart/form-data")
    assert r.status_code == 403
    data = {"channel": "absa", "file": (io.BytesIO(pdf(out, MWILA_ID, "absa")), "a.pdf")}
    r = c.post(f"/api/cases/{MWILA_ID}/upload", headers=h, data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    audit = c.get(f"/api/cases/{MWILA_ID}", headers=h).json["audit"]
    assert audit[-1]["action"] == "upload_statement" and audit[-1]["user"] == "rm.chanda"
