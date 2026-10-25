import pytest

from insaka.agent import NoChat
from insaka.api import create_app
from insaka.generator import MWILA_ID, generate


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    out = tmp_path_factory.mktemp("api")
    generate(5, 42, out, pdfs=False)
    app = create_app(out, out / "cases", out / "agent", label_method="rules",
                     memo_chat=NoChat(), registry={})
    return app.test_client()


def call(client, method, path, user=None, body=None):
    headers = {"X-User": user} if user else {}
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
