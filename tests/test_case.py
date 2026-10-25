import json

import pytest

from insaka.agent import NoChat, run_case
from insaka.case import NotAllowed, load_case
from insaka.generator import MWILA_ID, generate


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("case")
    generate(5, 42, out, pdfs=False)
    return out


def prepared(data, tmp_path, cid=MWILA_ID, registry=None):
    _, _, case = run_case(cid, "rules", data, cases_dir=tmp_path, agent_dir=tmp_path,
                          registry=registry or {}, label_method="rules", memo_chat=NoChat())
    return case


def test_full_workflow_with_roles_maker_checker_and_audit(data, tmp_path):
    case = prepared(data, tmp_path)
    assert case.status == "awaiting_rm"

    with pytest.raises(NotAllowed):
        case.approver_decide("approver.banda", "approved", "too early")   # not submitted yet
    with pytest.raises(NotAllowed):
        case.rm_edit("approver.banda", "Summary", "x")                   # not an RM
    case.rm_edit("manager.zulu", "Summary", "Edited by the RM.")
    case.rm_submit("manager.zulu", "Ready")

    with pytest.raises(NotAllowed, match="maker-checker"):
        case.approver_decide("manager.zulu", "approved", "my own case")
    with pytest.raises(NotAllowed, match="reason"):
        case.approver_decide("approver.banda", "approved", "")
    with pytest.raises(NotAllowed, match="recorded approval"):
        case.disburse("approver.banda")
    case.approver_decide("approver.banda", "approved", "Seasonal income covers the instalment.")

    with pytest.raises(NotAllowed):
        case.disburse("auditor.phiri")
    payout = case.disburse("approver.banda")
    assert payout["sandbox"] and payout["transaction_id"].startswith("SBX-")
    assert payout["amount"] == 25000 and case.status == "disbursed"

    reloaded = load_case(MWILA_ID, tmp_path)
    assert reloaded.status == "disbursed"
    assert reloaded.data["memo"]["sections"][0]["text"] == "Edited by the RM."
    actions = [(e["action"], e["user"]) for e in reloaded.audit_log()]
    assert actions == [("prepare", "insaka.agent"), ("edit_memo", "manager.zulu"),
                       ("submit", "manager.zulu"), ("decide", "approver.banda"),
                       ("disburse", "approver.banda")]
    assert reloaded.audit_log()[1]["details"]["before"] != "Edited by the RM."
    view = reloaded.view("auditor.phiri")
    assert view["case"]["status"] == "disbursed" and len(view["audit"]) == 5


def test_declined_case_cannot_be_paid(data, tmp_path):
    case = prepared(data, tmp_path)
    case.rm_submit("rm.chanda")
    case.approver_decide("approver.banda", "declined", "Overdraft dependence.")
    with pytest.raises(NotAllowed):
        case.disburse("approver.banda")


def test_stopped_case_has_nothing_to_submit(data, tmp_path):
    clients = json.loads((data / "clients.json").read_text("utf-8"))
    cid = next(c["client_id"] for c in clients[1:] if c["application"]["pacra_registered"])
    case = prepared(data, tmp_path, cid, registry={"pacra_not_found": [cid]})
    assert case.status == "escalated"
    with pytest.raises(NotAllowed):
        case.rm_submit("rm.chanda")
