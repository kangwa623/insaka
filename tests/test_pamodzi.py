import json

import pytest

from insaka.agent import NoChat, run_case
from insaka.case import load_ledger
from insaka.demo import seed
from insaka.generator import MWILA_ID, generate
from insaka.pamodzi import monthly_flows

OFFLINE = {"label_method": "rules", "memo_chat": NoChat(), "registry": {}}


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("pamodzi")
    generate(30, 42, out, pdfs=False)
    return out, json.loads((out / "ground_truth.json").read_text("utf-8"))


def flows(data, tmp_path, cid):
    out, _ = data
    run_case(cid, "rules", out, cases_dir=tmp_path, agent_dir=tmp_path, **OFFLINE)
    return monthly_flows(load_ledger(cid, tmp_path)), load_ledger(cid, tmp_path)


def test_flows_add_up_and_leave_out_own_transfers(data, tmp_path):
    p, ledger = flows(data, tmp_path, MWILA_ID)
    assert p["balance_check"]["mismatches"] == []
    own = [r for r in ledger if r["category"] == "own_account_transfer"]
    assert own and set(p["totals"]["rows_own"]) == {r["row_id"] for r in own}
    credits = sum(r["amount"] for r in ledger if r["direction"] == "credit" and r not in own)
    assert p["totals"]["in"] == pytest.approx(credits)
    for m in p["months"]:
        assert m["in"] == pytest.approx(sum(c["in"] for c in m["channels"].values()))
        rows = {r["row_id"]: r for r in ledger}
        assert m["in"] == pytest.approx(sum(rows[i]["amount"] for i in m["rows_in"]))


def test_edited_statement_fails_the_balance_check(data, tmp_path):
    _, truth = data
    cid = next(c for c, t in truth.items() if t["tamper"])
    p, _ = flows(data, tmp_path, cid)
    planted = truth[cid]["tamper"]
    assert any(m["channel"] == planted["channel"] for m in p["balance_check"]["mismatches"])


def test_seed_puts_cases_at_every_stage(data, tmp_path):
    out, _ = data
    done = seed(out, tmp_path, label_method="rules")
    assert set(done.values()) >= {"awaiting_rm", "submitted", "approved", "disbursed", "declined"}
