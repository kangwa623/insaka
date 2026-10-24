"""Repayment outcomes from a latent risk model.

The true model rewards stable, well-covered cash flow and penalises overdraft
dependence and reliance on one customer. Seasonality on its own is *not* penalised:
volatility is measured after removing the expected seasonal pattern.
"""

from datetime import date, timedelta

import numpy as np

from ..taxonomy import INCOME_CATEGORIES
from .profiles import instalment
from .seasons import SEASONAL, STATEMENT_END, statement_months

TARGET_DEFAULT_RATE = 0.15


def true_features(entry: dict, result: dict) -> dict:
    p, h = entry["profile"], entry["hidden"]
    months = [f"{y}-{m:02d}" for y, m in statement_months(p["months_of_history"])]
    income = {k: 0.0 for k in months}
    customer = {}
    committed = {k: 0.0 for k in months}
    for ledger in result["ledgers"].values():
        for r in ledger:
            key = f"{r['ts']:%Y-%m}"
            if r["true_category"] in INCOME_CATEGORIES:
                income[key] += r["true_amount"]
            if r["true_category"] == "customer_payment":
                customer[r["counterparty"]] = customer.get(r["counterparty"], 0) + r["true_amount"]
            if r["true_category"] in ("input_purchase", "rent", "wages", "loan_repayment"):
                committed[key] += r["true_amount"]

    season = SEASONAL[h["season"]]
    deseasoned = np.array([income[k] / season[int(k[-2:])] for k in months])
    raw = np.array([income[k] for k in months])
    surplus = np.mean([income[k] - committed[k] for k in months])
    app = p["application"]
    new_instalment = instalment(app["requested_amount"], app["tenor_months"])

    return {
        "mean_monthly_income": round(float(raw.mean()), 2),
        "raw_income_cv": round(float(raw.std() / raw.mean()), 4),
        "deseasoned_income_cv": round(float(deseasoned.std() / deseasoned.mean()), 4),
        "peak_to_median": round(float(raw.max() / np.median(raw)), 3),
        "overdraft_day_share": round(_overdraft_day_share(result, p["months_of_history"]), 4),
        "top_customer_share": round(max(customer.values()) / sum(customer.values()), 4)
        if customer else 0.0,
        "mean_monthly_surplus": round(float(surplus), 2),
        "new_instalment": round(new_instalment, 2),
        "debt_service_coverage": round(float(surplus / new_instalment), 3),
    }


def _overdraft_day_share(result: dict, n_months: int) -> float:
    """Share of calendar days the Absa account closed below zero."""
    y, m = statement_months(n_months)[0]
    day = date(y, m, 1)
    rows = result["ledgers"]["absa"]
    balance = result["opening"]["absa"]
    i, negative, total = 0, 0, 0
    while day <= STATEMENT_END:
        while i < len(rows) and rows[i]["ts"].date() <= day:
            balance = rows[i]["balance"]
            i += 1
        negative += balance < 0
        total += 1
        day += timedelta(days=1)
    return negative / total


def risk_logit(entry: dict, f: dict) -> float:
    """Everything except the intercept, which is calibrated across the cohort."""
    app, p, h = entry["profile"]["application"], entry["profile"], entry["hidden"]
    bureau = {"adverse": 1.3, "no_hit": 0.3, "clean": 0.0}[app["bureau_status"]]
    application = (bureau - 0.04 * p["years_trading"] - 0.3 * app["pacra_registered"]
                   - 0.2 * app["tpin_registered"])
    coverage = float(np.clip(f["debt_service_coverage"], 0.1, 20))
    statement = (2.2 * f["deseasoned_income_cv"] + 3.0 * f["overdraft_day_share"]
                 + 2.5 * max(0.0, f["top_customer_share"] - 0.4) - 1.1 * np.log(coverage)
                 + 0.6 * ("drought_shock" in h["findings"]))
    return float(application + statement)


def assign_outcomes(entries: list[dict], rng: np.random.Generator) -> None:
    """Calibrate the intercept to the target default rate, then draw outcomes."""
    logits = np.array([e["logit"] + rng.normal(0, 0.4) for e in entries])
    lo, hi = -15.0, 15.0
    for _ in range(60):
        mid = (lo + hi) / 2
        rate = np.mean(1 / (1 + np.exp(-(logits + mid))))
        lo, hi = (mid, hi) if rate < TARGET_DEFAULT_RATE else (lo, mid)
    pds = 1 / (1 + np.exp(-(logits + lo)))
    for e, pd in zip(entries, pds):
        e["pd"] = round(float(pd), 4)
        e["defaulted"] = bool(rng.random() < pd)
