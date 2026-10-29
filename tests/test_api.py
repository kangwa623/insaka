import pytest

from insaka.agent import NoChat
from insaka.api import create_app
from insaka.generator import MWILA_ID, generate

from conftest import auth_headers


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    out = tmp_path_factory.mktemp("api")
    generate(5, 42, out, pdfs=False)
    app = create_app(out, out / "cases", out / "agent", security_dir=out / "security",
                     label_method="rules", memo_chat=NoChat(), registry={})
    return app.test_client()


def call(client, method, path, user=None, body=None):
    headers = auth_headers(client.application, user) if user else {}
    return getattr(client, method)(f"/api{path}", headers=headers, json=body)


def test_workflow_over_http_with_server_side_roles(client):
    assert call(client, "get", "/cases").status_code == 401   # no one signed in
    cases = call(client, "get", "/cases", "rm.chanda").json
    assert cases[0]["client_id"] == MWILA_ID and cases[0]["status"] == "not_started"

    assert call(client, "post", f"/cases/{MWILA_ID}/run", "approver.banda").status_code == 403
    r = call(client, "post", f"/cases/{MWILA_ID}/run", "rm.chanda", {"mode": "rules"})
    assert r.status_code == 200 and r.json["case"]["status"] == "awaiting_rm"
    assert len(r.json["case"]["agent_run"]["steps"]) == 11
    ledger = call(client, "get", f"/cases/{MWILA_ID}/ledger", "rm.chanda").json
    ids = {row["row_id"] for row in ledger}
    for s in r.json["case"]["memo"]["sections"]:
        for span in s["figures"]:
            assert set(span["rows"]) <= ids   # every linked figure opens real rows

    r = call(client, "post", f"/cases/{MWILA_ID}/decide", "approver.banda",
             {"decision": "approved", "note": "early"})
    assert r.status_code == 403   # not submitted yet
    assert call(client, "post", f"/cases/{MWILA_ID}/edit", "rm.chanda",
                {"section": "Summary", "text": "RM wording."}).status_code == 200
    assert call(client, "post", f"/cases/{MWILA_ID}/submit", "manager.zulu", {}).status_code == 200
    r = call(client, "post", f"/cases/{MWILA_ID}/decide", "manager.zulu",
             {"decision": "approved", "note": "mine"})
    assert r.status_code == 403 and "maker-checker" in r.json["error"]
    assert call(client, "post", f"/cases/{MWILA_ID}/run", "rm.chanda").status_code == 403
    assert call(client, "post", f"/cases/{MWILA_ID}/decide", "approver.banda",
                {"decision": "approved", "note": "Covers the instalment."}).status_code == 200
    r = call(client, "post", f"/cases/{MWILA_ID}/disburse", "rm.chanda")
    assert r.status_code == 200 and r.json["case"]["status"] == "disbursed"
    assert r.json["result"]["transaction_id"].startswith("SBX-")
    actions = [e["action"] for e in r.json["audit"]]
    assert actions == ["prepare", "edit_memo", "submit", "decide", "disburse"]


def test_unknown_case_is_404(client):
    assert call(client, "get", "/cases/ZM-9999", "rm.chanda").status_code == 404


def test_evaluation_results_need_sign_in():
    app = create_app()
    c = app.test_client()
    assert call(c, "get", "/evaluation").status_code == 401
    raw = call(c, "get", "/evaluation", "auditor.phiri")
    assert b"NaN" not in raw.data   # must parse as strict JSON in the browser
    r = raw.json
    assert set(r) == {"parsing", "labelling", "labelling_holdout", "scoring", "memo", "agent"}
    assert r["scoring"]["holdout"]["models"]["logistic"]["auroc"] > 0.8


def test_pipeline_fields_and_pamodzi(client):
    rows = {r["client_id"]: r for r in call(client, "get", "/cases", "rm.chanda").json}
    mwila = rows[MWILA_ID]
    assert mwila["stage_since"] and mwila["prepared_in_seconds"] is not None
    p = call(client, "get", f"/cases/{MWILA_ID}/pamodzi", "rm.chanda").json
    assert p["channels"] and p["balance_check"]["mismatches"] == []


def test_cross_origin_headers(monkeypatch):
    monkeypatch.setenv("INSAKA_CORS_ORIGINS", "https://insaka.web.app")
    c = create_app().test_client()
    ok = c.get("/api/users", headers={"Origin": "https://insaka.web.app"})
    assert ok.headers["Access-Control-Allow-Origin"] == "https://insaka.web.app"
    pre = c.options("/api/cases/MWILA-001/submit", headers={
        "Origin": "https://insaka.web.app", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization, Content-Type"})
    assert pre.status_code == 200 and "Authorization" in pre.headers["Access-Control-Allow-Headers"]
    other = c.get("/api/users", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in other.headers


def test_without_built_screens_visitors_go_to_the_site(tmp_path):
    c = create_app(frontend_dir=tmp_path / "missing").test_client()
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"] == "https://insaka.web.app/"
    r = c.get("/upload/abc123")
    assert r.headers["Location"] == "https://insaka.web.app/upload/abc123"
