import json
from dataclasses import replace

import pytest
from reportlab.pdfgen.canvas import Canvas

from insaka.evaluation.parsing import evaluate
from insaka.generator import MWILA_ID, generate
from insaka.generator.findings import INJECTION_TEXTS
from insaka.ledger import LedgerRow, Statement
from insaka.parsing import ParseError, cross_match, parse_statement, read_case, reconcile
from insaka.parsing.layouts import detect_layout


@pytest.fixture(scope="session")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("statements")
    generate(30, 42, out, pdfs=True)
    clients = {c["client_id"]: c for c in json.loads((out / "clients.json").read_text("utf-8"))}
    truth = json.loads((out / "ground_truth.json").read_text("utf-8"))
    return out, clients, truth


def case_paths(out, client):
    return [out / "statements" / f"{client['client_id']}_{c}.pdf" for c in client["channels"]]


def test_parser_and_checks_match_ground_truth(data):
    out, _, truth = data
    result = evaluate(out)
    assert result["row_count_mismatches"] == 0
    assert result["row_exact_match"] == 1.0
    tamper = result["tamper_detection"]
    assert tamper["planted"] == sum(bool(t["tamper"]) for t in truth.values()) >= 2
    assert tamper["precision"] == tamper["recall"] == 1.0
    transfers = result["transfer_matching"]
    assert transfers["precision"] == transfers["recall"] == 1.0
    assert transfers["tampered_transfers_disputed"] == transfers["tampered_transfers"]


def test_mwila_case_passes_with_trust_levels(data):
    out, clients, _ = data
    statements, report = read_case(case_paths(out, clients[MWILA_ID]))
    assert report["passed"] and report["flagged_rows"] == []
    absa, mtn = statements
    assert (absa.holder, absa.business, absa.account) == \
        ("Mwila Tembo", "Tembo Maize & Inputs", "****4821")
    assert {r.trust for r in absa.rows} == {"Verified"}
    transfer_rows = {pair[0] for pair in report["transfers"]["matched"]}
    assert transfer_rows
    for row in mtn.rows:
        assert row.trust == ("Verified" if row.row_id in transfer_rows else "Cross-checked")


def test_tampered_statement_is_unverified(data):
    out, clients, truth = data
    cid = next(c for c, t in truth.items() if t["tamper"])
    planted = truth[cid]["tamper"]
    statements, report = read_case(case_paths(out, clients[cid]))
    assert planted["row_id"] in report["flagged_rows"] and not report["passed"]
    edited = next(s for s in statements if s.channel == planted["channel"])
    assert {r.trust for r in edited.rows} == {"Unverified"}
    brk = next(b for c in report["statements"] for b in c["breaks"])
    assert brk["shown_amount"] == planted["shown_amount"]
    assert brk["implied_amount"] == planted["original_amount"]


def test_injected_text_is_read_as_plain_data(data):
    out, clients, truth = data
    cid = next(c for c, t in truth.items() if t["injection_rows"])
    statements, _ = read_case(case_paths(out, clients[cid]))
    rows = {r.row_id: r for s in statements for r in s.rows}
    for row_id in truth[cid]["injection_rows"]:
        assert rows[row_id].description in INJECTION_TEXTS


# ---- checks on hand-built ledgers ------------------------------------------------------

def _statement(channel, amounts, opening=100.0, account="****1", refs=None, closing=None):
    rows, balance = [], opening
    for i, signed in enumerate(amounts, start=1):
        balance += signed
        rows.append(LedgerRow(f"T-{channel.upper()}-{i:04d}", channel, "2026-01-01", "", "x",
                              (refs or {}).get(i, f"{channel}{i}"),
                              "credit" if signed > 0 else "debit", abs(signed), balance, 1))
    return Statement(f"T-{channel.upper()}", channel, "A", "B", account, "", opening,
                     balance if closing is None else closing, "t.pdf", rows)


def test_reconcile_pinpoints_an_edited_amount():
    s = _statement("absa", [50, -20, 30])
    s.rows[1] = replace(s.rows[1], amount=200.0)
    check = reconcile(s)
    assert [b["row_id"] for b in check["breaks"]] == ["T-ABSA-0002"]
    assert check["breaks"][0]["implied_amount"] == 20.0


def test_reconcile_catches_a_wrong_closing_balance():
    check = reconcile(_statement("absa", [50, -20], closing=999.0))
    assert check["breaks"] == [] and not check["closing_matches"] and not check["reconciles"]


def test_cross_match_disputes_an_amount_that_differs():
    wallet = _statement("mtn", [-300.0], opening=500.0, account="096****1", refs={1: "R1"})
    wallet.rows[0].description = "Transfer to Bank ABSA ****1"
    absa = _statement("absa", [310.0], refs={1: "R1"})
    result = cross_match(absa, [wallet])
    assert result["matched"] == [] and len(result["mismatched"]) == 1


def test_unknown_layout_and_textless_pdf_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        detect_layout("Some Other Bank Statement")
    blank = tmp_path / "scan.pdf"
    canvas = Canvas(str(blank))
    canvas.showPage()
    canvas.save()
    with pytest.raises(ParseError):
        parse_statement(blank)
