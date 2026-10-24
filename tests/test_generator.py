import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pypdf import PdfReader
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_predict

from insaka.generator import MWILA_ID, generate
from insaka.generator.findings import INJECTION_TEXTS
from insaka.generator.render_pdf import render_statement

SEED = 42


def load(out: Path):
    clients = {c["client_id"]: c for c in json.loads((out / "clients.json").read_text("utf-8"))}
    truth = json.loads((out / "ground_truth.json").read_text("utf-8"))
    return clients, truth


def ledger(out: Path, client_id: str, channel: str) -> list[dict]:
    with open(out / "transactions" / f"{client_id}_{channel}.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("amount", "balance", "true_amount"):
            r[k] = float(r[k])
    return rows


@pytest.fixture(scope="session")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generate(150, SEED, out, pdfs=False)
    clients, truth = load(out)
    return out, clients, truth


def unreconciled_rows(rows: list[dict], opening: float) -> list[str]:
    bad, previous = [], opening
    for r in rows:
        signed = r["amount"] if r["direction"] == "credit" else -r["amount"]
        if abs(previous + signed - r["balance"]) > 0.011:
            bad.append(r["row_id"])
        previous = r["balance"]
    return bad


def test_ledgers_reconcile_except_the_tampered_row(data):
    out, clients, truth = data
    n_tampered = 0
    for cid, client in clients.items():
        tamper = truth[cid]["tamper"]
        for channel in client["channels"]:
            bad = unreconciled_rows(ledger(out, cid, channel),
                                    truth[cid]["opening_balances"][channel])
            if tamper and tamper["channel"] == channel:
                assert bad == [tamper["row_id"]]
                n_tampered += 1
            else:
                assert bad == [], f"{cid} {channel}"
    assert 5 <= n_tampered <= 10


def monthly_income(rows_by_channel: list[list[dict]]) -> dict:
    income = {}
    for rows in rows_by_channel:
        for r in rows:
            if r["true_category"] in ("customer_payment", "cash_deposit"):
                income[r["date"][:7]] = income.get(r["date"][:7], 0) + r["true_amount"]
    return income


def test_mwila_story(data):
    out, clients, truth = data
    mwila, gt = clients[MWILA_ID], truth[MWILA_ID]
    assert mwila["application"]["requested_amount"] == 25_000
    assert mwila["town"] == "Chipata" and mwila["months_of_history"] == 12
    assert gt["tamper"] is None and gt["injection_rows"] == [] and gt["defaulted"] is False

    rows = {c: ledger(out, MWILA_ID, c) for c in mwila["channels"]}
    income = monthly_income(list(rows.values()))
    assert income["2026-05"] >= 1.8 * np.median(list(income.values()))
    assert max(income, key=income.get) == "2026-05"

    supplier_months = {r["date"][:7] for rs in rows.values() for r in rs
                       if r["true_category"] == "input_purchase"
                       and "CHIPATA AGRO INPUTS" in r["description"].upper()}
    assert supplier_months == set(income)  # paid every month


def test_mwila_is_the_same_for_any_seed(data, tmp_path):
    out, clients, _ = data
    generate(3, 7, tmp_path, pdfs=False)
    for channel in clients[MWILA_ID]["channels"]:
        name = f"{MWILA_ID}_{channel}.csv"
        assert (tmp_path / "transactions" / name).read_bytes() == \
            (out / "transactions" / name).read_bytes()


def test_same_seed_same_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(10, SEED, a, pdfs=False)
    generate(10, SEED, b, pdfs=False)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files
    for f in files:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_transfer_pairs_match(data):
    out, clients, truth = data
    checked = 0
    for cid, client in clients.items():
        rows = {r["row_id"]: r for c in client["channels"] for r in ledger(out, cid, c)}
        for wallet_id, absa_id in truth[cid]["transfer_pairs"]:
            w, a = rows[wallet_id], rows[absa_id]
            assert "ABSA" in absa_id and "ABSA" not in wallet_id
            assert (w["direction"], a["direction"]) == ("debit", "credit")
            assert w["true_amount"] == a["true_amount"] and w["reference"] == a["reference"]
            checked += 1
    assert checked > 100


def test_planted_findings_show_in_the_data(data):
    _, _, truth = data
    for cid, gt in truth.items():
        f, findings = gt["true_features"], gt["findings"]
        if "dominant_customer" in findings:
            assert f["top_customer_share"] >= 0.5, cid
        else:
            assert f["top_customer_share"] < 0.4, cid
        if "heavy_overdraft" in findings:
            assert f["overdraft_day_share"] >= 0.3, cid
        else:
            assert f["overdraft_day_share"] < 0.1, cid
        if "seasonal_income" in findings:
            assert f["peak_to_median"] >= 1.5, cid
    counts = {k: sum(k in gt["findings"] for gt in truth.values())
              for k in ("seasonal_income", "drought_shock", "irregular_inflows",
                        "heavy_overdraft", "dominant_customer")}
    assert all(n >= 5 for n in counts.values()), counts


def test_injection_rows_keep_their_true_category(data):
    out, clients, truth = data
    injected = {cid: gt["injection_rows"] for cid, gt in truth.items() if gt["injection_rows"]}
    assert len(injected) == 3
    for cid, ids in injected.items():
        rows = {r["row_id"]: r for c in clients[cid]["channels"] for r in ledger(out, cid, c)}
        for row_id in ids:
            assert rows[row_id]["description"] in INJECTION_TEXTS
            assert rows[row_id]["true_category"] == "customer_payment"


def test_cohort_balance(data):
    _, clients, truth = data
    assert len(clients) == 151
    assert 0.10 <= np.mean([gt["defaulted"] for gt in truth.values()]) <= 0.20
    women = np.mean([c["gender"] == "F" for c in clients.values()])
    assert 0.35 <= women <= 0.65
    assert len({c["province"] for c in clients.values()}) == 10
    amounts = [c["application"]["requested_amount"] for c in clients.values()]
    assert min(amounts) >= 10_000 and max(amounts) <= 1_000_000


def test_statement_features_add_signal(data):
    """The ablation the Evaluation screen will run, on true features: statements must matter."""
    _, clients, truth = data
    ids = sorted(clients)
    y = np.array([truth[c]["defaulted"] for c in ids])
    app = np.array([[c["years_trading"], c["application"]["pacra_registered"],
                     c["application"]["tpin_registered"],
                     c["application"]["bureau_status"] == "adverse",
                     c["application"]["bureau_status"] == "no_hit",
                     np.log(c["application"]["requested_amount"])]
                    for c in (clients[i] for i in ids)], dtype=float)
    stmt = np.array([[f["deseasoned_income_cv"], f["overdraft_day_share"],
                      f["top_customer_share"], np.log(max(f["debt_service_coverage"], 0.1))]
                     for f in (truth[i]["true_features"] for i in ids)])

    def cv_auc(X):
        X = (X - X.mean(0)) / (X.std(0) + 1e-9)
        p = cross_val_predict(LogisticRegression(max_iter=1000), X, y, cv=5,
                              method="predict_proba")[:, 1]
        return roc_auc_score(y, p)

    assert cv_auc(np.hstack([app, stmt])) - cv_auc(app) > 0.05


def test_statement_pdf_renders(data, tmp_path):
    out, clients, truth = data
    mwila = clients[MWILA_ID]
    rows = ledger(out, MWILA_ID, "absa")
    for r in rows:
        r["ts"] = datetime.fromisoformat(f"{r['date']}T{r['time']}")
    path = tmp_path / "mwila_absa.pdf"
    render_statement(path, "absa", mwila, rows, truth[MWILA_ID]["opening_balances"]["absa"])
    text = "".join(page.extract_text() for page in PdfReader(path).pages)
    assert "SYNTHETIC DATA" in text
    assert rows[0]["reference"] in text and rows[-1]["reference"] in text
