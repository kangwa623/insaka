import json

import numpy as np
import pytest

from insaka.findings import detect_findings
from insaka.generator import MWILA_ID, generate
from insaka.generator.findings import FINDINGS
from insaka.scoring.cohort import client_record, prepare_case
from insaka.features import compute_features

EXACT = ("mean_monthly_income", "raw_income_cv", "deseasoned_income_cv", "peak_to_median",
         "overdraft_day_share", "mean_monthly_surplus", "new_instalment", "debt_service_coverage")


@pytest.fixture(scope="session")
def cohort(tmp_path_factory):
    out = tmp_path_factory.mktemp("features")
    generate(120, 5, out, pdfs=False)
    clients = json.loads((out / "clients.json").read_text("utf-8"))
    truth = json.loads((out / "ground_truth.json").read_text("utf-8"))
    records = [client_record(out, "truth", (c, truth[c["client_id"]])) for c in clients]
    return out, {c["client_id"]: c for c in clients}, truth, records


def test_features_match_the_generators_truth(cohort):
    *_, records = cohort
    for name in EXACT:
        ours = np.array([r["features"][name] for r in records])
        true = np.array([r["true_features"][name] for r in records])
        assert np.allclose(ours, true, rtol=0.01, atol=1e-3), name
    # "TRF FROM BANDA C" can't always be tied to one customer, so allow a little slack.
    top = np.array([r["features"]["top_customer_share"] - r["true_features"]["top_customer_share"]
                    for r in records])
    assert np.abs(top).max() < 0.1


def test_every_statement_figure_traces_to_rows_that_add_up(cohort):
    out, clients, truth, _ = cohort
    statements, report, corrections = prepare_case(out, clients[MWILA_ID], truth[MWILA_ID], "truth")
    figures = compute_features(statements, clients[MWILA_ID], corrections)
    rows = {r.row_id: r for s in statements for r in s.rows}
    for f in figures.values():
        assert f.rows or f.detail.get("source") == "application", f.name
        assert set(f.rows) <= set(rows)
    by_month = figures["monthly_income"].detail["by_month"]
    for month in by_month.values():
        assert abs(sum(rows[r].amount for r in month["rows"]) - month["value"]) < 0.01
    assert figures["peak_month"].value == "2026-05"   # Mwila's harvest spike


def test_tampered_amounts_are_replaced_by_what_the_balances_show(cohort):
    out, clients, truth, records = cohort
    cid = next(c for c, t in truth.items() if t["tamper"])
    rec = next(r for r in records if r["client_id"] == cid)
    assert not rec["verification_passed"]
    assert rec["features"]["mean_monthly_income"] == pytest.approx(
        truth[cid]["true_features"]["mean_monthly_income"], rel=0.01)


def test_findings_are_detected(cohort):
    *_, records = cohort
    for f in FINDINGS:
        tp = sum(f in r["findings"] and f in r["true_findings"] for r in records)
        fp = sum(f in r["findings"] and f not in r["true_findings"] for r in records)
        fn = sum(f not in r["findings"] and f in r["true_findings"] for r in records)
        if tp + fn:
            assert 2 * tp / (2 * tp + fp + fn) >= 0.85, f


def test_mwila_is_seasonal_not_risky(cohort):
    out, clients, truth, _ = cohort
    statements, report, corrections = prepare_case(out, clients[MWILA_ID], truth[MWILA_ID], "truth")
    findings = detect_findings(compute_features(statements, clients[MWILA_ID], corrections),
                               clients[MWILA_ID])
    assert set(findings) == {"seasonal_income"} and not findings["seasonal_income"]["risk"]
