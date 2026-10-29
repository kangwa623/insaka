import json
import re

import pytest

from insaka.agent import NoChat
from insaka.agent.tools import TOOLS
from insaka.api import create_app
from insaka.case import NotAllowed, load_case
from insaka.generator import MWILA_ID, generate
from insaka.security import CircuitBreaker, EventLog, valid_client_id

from conftest import auth_headers


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    out = tmp_path_factory.mktemp("security")
    generate(4, 42, out, pdfs=False)
    app = create_app(out, out / "cases", out / "agent", uploads_dir=out / "uploads",
                     security_dir=out / "security", label_method="rules", memo_chat=NoChat(),
                     registry={})
    return out, app


def post(app, user, path, body=None):
    return app.test_client().post(f"/api{path}", headers=auth_headers(app, user), json=body or {})


def test_object_level_access_and_maker_checker(env):
    out, app = env
    assert post(app, "rm.chanda", f"/cases/{MWILA_ID}/run", {"mode": "rules"}).status_code == 200
    # Another RM cannot work Chanda's case; a manager can.
    assert post(app, "rm.mutale", f"/cases/{MWILA_ID}/submit").status_code == 403
    assert post(app, "auditor.phiri", f"/cases/{MWILA_ID}/escalate",
                {"to": "fraud", "reason": "x"}).status_code == 403
    assert post(app, "manager.zulu", f"/cases/{MWILA_ID}/submit").status_code == 200
    r = post(app, "manager.zulu", f"/cases/{MWILA_ID}/decide", {"decision": "approved", "note": "ok"})
    assert r.status_code == 403 and "maker-checker" in r.json["error"]


def test_escalation_is_resolved_by_someone_else(env):
    out, app = env
    r = post(app, "approver.banda", f"/cases/{MWILA_ID}/escalate",
             {"to": "credit_risk", "reason": "Second opinion on the seasonal surplus."})
    assert r.status_code == 200 and r.json["case"]["status"] == "escalated"
    assert post(app, "approver.banda", f"/cases/{MWILA_ID}/resolve",
                {"resolution": "return", "note": "self"}).status_code == 403
    r = post(app, "manager.zulu", f"/cases/{MWILA_ID}/resolve",
             {"resolution": "return", "note": "Reviewed; fine."})
    assert r.status_code == 200 and r.json["case"]["status"] == "awaiting_rm"
    assert post(app, "rm.chanda", f"/cases/{MWILA_ID}/escalate",
                {"to": "nowhere", "reason": "x"}).status_code == 403


def test_delegated_limit_and_high_risk_gate(env):
    out, app = env
    case = load_case(MWILA_ID, out / "cases")
    case.data["requested_amount"] = 750_000
    case.data["submitted_by"] = "rm.chanda"
    case.data["status"] = "submitted"
    case.save()
    with pytest.raises(NotAllowed, match="delegated limit"):
        case.approver_decide("approver.banda", "approved", "big")
    case.data["requested_amount"] = 25_000
    case.data["score"]["band"] = "High"
    case.data["human_escalations"] = []          # no credit-risk review on record
    with pytest.raises(NotAllowed, match="credit-risk escalation"):
        case.approver_decide("approver.banda", "approved", "risky")
    case.approver_decide("approver.banda", "declined", "Too risky for now.")
    assert case.status == "declined"


def test_input_validation_blocks_path_traversal(env):
    out, app = env
    c = app.test_client()
    h = auth_headers(app, "rm.chanda")
    assert not valid_client_id("../../etc") and not valid_client_id("MWILA-001.json")
    for bad in ("..", "x", "MWILA-001x", "ZM-1"):
        assert c.get(f"/api/cases/{bad}", headers=h).status_code == 404
    assert c.get("/api/upload/forged-token").status_code == 404


def test_security_headers_and_no_stack_traces(env):
    out, app = env
    r = app.test_client().get("/api/health")
    assert r.status_code == 200 and r.json["checks"]["risk_model_verified"]
    for h in ("X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy",
              "Strict-Transport-Security", "Referrer-Policy"):
        assert h in r.headers
    assert r.headers["Cache-Control"] == "no-store"


def test_event_log_is_tamper_evident(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    for i in range(3):
        log.record("login_failed", user=f"u{i}")
    assert log.verify()["intact"]
    lines = (tmp_path / "events.jsonl").read_text("utf-8").splitlines()
    edited = json.loads(lines[1])
    edited["user"] = "someone-else"
    lines[1] = json.dumps(edited)
    (tmp_path / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")
    assert log.verify() == {"intact": False, "entries": 3, "broken_at": 2}


def test_circuit_breaker_opens_after_repeated_failures():
    b = CircuitBreaker(failures=3, window_s=60, cooldown_s=60)
    assert not b.failure("e1") and not b.failure("e2")
    assert b.failure("e3") and b.is_open() and b.state()["state"] == "open"


def test_tampered_risk_model_is_not_loaded(tmp_path):
    from insaka.scoring import model as risk
    path = tmp_path / "m.joblib"
    risk.save({"model": None, "columns": []}, path)
    assert risk.load(path)["columns"] == []
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(risk.ModelIntegrityError):
        risk.load(path)


def test_agent_has_no_power_to_decide_or_pay():
    assert set(TOOLS) == {"read_statement", "request_documents", "verify_statements",
                          "label_transactions", "check_registration", "check_tax_status",
                          "check_credit_bureau", "score_risk", "draft_memo", "escalate",
                          "submit_for_review"}
    assert not any(re.search(r"approv|declin|disburs|pay", t) for t in TOOLS)


def test_prompts_carry_no_personal_data(env):
    """What the model sees: masked rows and facts, never names, phones or account numbers."""
    out, _ = env
    from insaka.agent import build_case
    from insaka.labelling.llm import batch_prompt, group_patterns
    from insaka.labelling.masking import mask_case
    from insaka.labelling.payees import summarise_payees
    case = build_case(MWILA_ID, out, label_method="rules", memo_chat=NoChat(), registry={})
    statements = [case.sources[ch]() for ch in case.client["channels"]]
    masked, _ = mask_case(statements)
    rows = [r for s in statements for r in s.rows]
    payees = summarise_payees(statements, masked)
    prompt = batch_prompt(group_patterns(rows, masked, payees), payees)
    owner = case.client["owner_name"].upper().split()
    assert not any(name in prompt.upper() for name in owner)
    assert not re.search(r"\d{3}\*{4}\d{3}", prompt)                   # masked phone numbers
    assert not any(acc in prompt for acc in case.client["channels"].values())
