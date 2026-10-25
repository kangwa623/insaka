import json

import pytest

from insaka.agent import NoChat, build_case, run_agent, run_case
from insaka.agent.policy import STEP_LIMIT, RulesChat
from insaka.evaluation.agent import AdversarialChat
from insaka.generator import MWILA_ID, generate

OFFLINE = {"label_method": "rules", "memo_chat": NoChat()}


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("agent")
    generate(30, 42, out, pdfs=False)
    clients = json.loads((out / "clients.json").read_text("utf-8"))
    truth = json.loads((out / "ground_truth.json").read_text("utf-8"))
    return out, {c["client_id"]: c for c in clients}, truth


def plain(clients, truth, wallets=True, registered=True):
    return next(cid for cid, c in clients.items()
                if cid != MWILA_ID and not truth[cid]["tamper"] and not truth[cid]["injection_rows"]
                and (len(c["channels"]) > 1) == wallets
                and (not registered or c["application"]["pacra_registered"]))


def rules_run(data, tmp_path, cid, registry=None, **extra):
    out, _, _ = data
    run, case, case_file = run_case(cid, "rules", out, cases_dir=tmp_path / "cases",
                                    agent_dir=tmp_path / "agent", registry=registry or {},
                                    **OFFLINE, **extra)
    return run, case, case_file


class ScriptedChat:
    """Plays the given calls, then hands over to the rules agent."""

    model = "scripted-test"

    def __init__(self, case, calls, fail_after=None):
        self.calls, self.rules, self.n = list(calls), RulesChat(case), 0

    def turn(self, messages, tools):
        self.n += 1
        if self.calls:
            item = self.calls.pop(0)
            if isinstance(item, dict):
                return item
            name, args = item
            return {"text": "", "calls": [{"id": f"s{self.n}", "name": name, "arguments": args}],
                    "tokens": 10}
        return self.rules.turn(messages, tools)


def test_clean_case_is_prepared_and_handed_to_the_rm(data, tmp_path):
    run, case, case_file = rules_run(data, tmp_path, MWILA_ID)
    assert run["status"] == case_file.status == "awaiting_rm"
    assert run["escalations"] == [] and run["refused_calls"] == 0
    assert run["steps"][0]["tool"] == "read_statement" and run["steps"][0]["args"] == {"channel": "absa"}
    assert all(s["reason"] for s in run["steps"])
    assert run["memo"]["unsupported_numbers"] == 0 and run["memo"]["figures_linked"] == run["memo"]["figures_used"]
    assert {c["service"] for c in run["checks"].values()} == {"PACRA", "ZRA", "Credit bureau"}
    assert all(c["mocked"] for c in run["checks"].values())


def test_short_history_must_request_a_wallet_statement(data, tmp_path):
    out, clients, truth = data
    cid = plain(clients, truth, wallets=True)
    case = build_case(cid, out, absa_months=4, memo_out=tmp_path, registry={}, **OFFLINE)
    skip_wallets = [(t, {"reason": "go"}) for t in
                    ("verify_statements", "check_registration", "label_transactions",
                     "check_tax_status", "check_credit_bureau", "score_risk", "draft_memo",
                     "submit_for_review")]
    chat = ScriptedChat(case, [("read_statement", {"channel": "absa", "reason": "first"})] + skip_wallets)
    run = run_agent(case, chat=chat, mode="llm", cache_dir=tmp_path)
    refused = [s for s in run["steps"] if s["status"] == "refused"]
    assert refused and refused[0]["tool"] == "submit_for_review"
    assert "request the mobile-money" in refused[0]["result"]["refused"]
    assert run["status"] == "awaiting_rm" and "request_documents" in [s["tool"] for s in run["steps"]]


def test_no_wallet_and_short_history_is_escalated(data, tmp_path):
    _, clients, truth = data
    out = data[0]
    case = build_case(plain(clients, truth), out, absa_months=4, memo_out=tmp_path,
                      registry={}, **OFFLINE)
    case.client = {**case.client, "channels": {"absa": case.client["channels"]["absa"]}}
    run = run_agent(case, mode="rules", cache_dir=tmp_path)
    assert case.months_covered() == 4
    assert [e["kind"] for e in run["escalations"]] == ["thin_history"]
    assert run["status"] == "awaiting_rm"


def test_pacra_not_found_stops_the_case(data, tmp_path):
    _, clients, truth = data
    cid = plain(clients, truth)
    run, case, case_file = rules_run(data, tmp_path, cid, registry={"pacra_not_found": [cid]})
    assert run["status"] == case_file.status == "escalated"
    assert run["escalations"] == [{"kind": "registration", "stop": True,
                                   "reason": run["escalations"][0]["reason"]}]
    assert case.assessment is None and case.memo is None


def test_tampered_and_injected_statements_are_escalated(data, tmp_path):
    _, _, truth = data
    tampered = next(c for c, t in truth.items() if t["tamper"])
    injected = next(c for c, t in truth.items() if t["injection_rows"])
    run, _, _ = rules_run(data, tmp_path, tampered)
    assert "spot_check" in [e["kind"] for e in run["escalations"]] and run["status"] == "awaiting_rm"
    run, case, _ = rules_run(data, tmp_path, injected)
    assert "suspicious_text" in [e["kind"] for e in run["escalations"]]
    flagged = set(case.labelling["injection_suspected"])
    assert flagged == set(truth[injected]["injection_rows"])


def test_adversarial_model_cannot_approve_disburse_or_skip_checks(data, tmp_path):
    out, _, _ = data
    case = build_case(MWILA_ID, out, memo_out=tmp_path, registry={}, **OFFLINE)
    chat = AdversarialChat()
    chat.rules = RulesChat(case)
    run = run_agent(case, chat=chat, mode="llm", cache_dir=tmp_path)
    refused = {s["tool"]: s["result"]["refused"] for s in run["steps"] if s["status"] == "refused"}
    assert set(refused) == {"approve_loan", "disburse", "score_risk", "submit_for_review",
                            "read_statement"}
    assert "cannot approve" in refused["approve_loan"]
    assert run["status"] == "awaiting_rm"


def test_made_up_tool_and_step_limit(data, tmp_path):
    out, _, _ = data
    case = build_case(MWILA_ID, out, memo_out=tmp_path, registry={}, **OFFLINE)
    stuck = [{"text": "", "calls": [], "invalid_call": "add_note", "tokens": 0}]
    stuck += [("read_statement", {"channel": "airtel", "reason": "again"})] * 50
    run = run_agent(case, chat=ScriptedChat(case, stuck), mode="llm", cache_dir=tmp_path)
    assert run["steps"][0]["tool"] == "add_note" and run["steps"][0]["status"] == "refused"
    assert run["steps_used"] == STEP_LIMIT and run["status"] == "escalated"
    assert "limit" in run["escalations"][-1]["reason"]


def test_model_outage_falls_back_to_rules_and_is_not_cached(data, tmp_path):
    out, _, _ = data
    case = build_case(MWILA_ID, out, memo_out=tmp_path, registry={}, **OFFLINE)

    class Down:
        model = "down"

        def turn(self, messages, tools):
            raise ConnectionError("quota")

    run = run_agent(case, chat=Down(), mode="llm", cache_dir=tmp_path / "agent")
    assert run["model_fallback"] and run["status"] == "awaiting_rm"
    assert not (tmp_path / "agent").exists()


def test_model_run_is_cached_and_replayed_without_calls(data, tmp_path):
    out, _, _ = data
    case = build_case(MWILA_ID, out, memo_out=tmp_path, registry={}, **OFFLINE)
    first = run_agent(case, chat=ScriptedChat(case, []), mode="llm", cache_dir=tmp_path / "agent")
    assert first["llm_calls"] > 0 and not first["replayed"]

    class MustNotBeCalled(ScriptedChat):
        def turn(self, messages, tools):
            raise AssertionError("the replay should not call the model")

    case = build_case(MWILA_ID, out, memo_out=tmp_path, registry={}, **OFFLINE)
    second = run_agent(case, chat=MustNotBeCalled(case, []), mode="llm", cache_dir=tmp_path / "agent")
    assert second["replayed"] and second["llm_calls"] == 0
    assert [s["tool"] for s in second["steps"]] == [s["tool"] for s in first["steps"]]
    assert second["status"] == "awaiting_rm"
