"""The pre-visit brief: what an RM should know before meeting the client.

Four parts, each built by code from the case and pointing at the figures or statement
lines behind it: the cash-flow trend (against what the business's season predicts),
products the client doesn't hold (rules on the figures; catalogue and holdings mocked),
open issues, and risk flags.
"""

import json
from pathlib import Path

from .features import Figure, season_for
from .findings import detect_findings
from .memo import FINDING_TEXT

PRODUCTS_PATH = Path("data/mocks/products.json")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
NEXT_STEP = {
    "awaiting_rm": "Review the memo and submit it to an approver.",
    "submitted": "Waiting for the approver's decision.",
    "approved": "Disburse through the MoMo sandbox.",
    "escalated": "The agent stopped this case: resolve the escalation first.",
    "disbursed": "Paid out; follow up on the first instalment.",
    "declined": "Declined; explain the reasons to the client.",
}


def _span(months: list[str]) -> str:
    a, b = months[0], months[-1]
    return f"{MONTHS[int(a[5:]) - 1]}–{MONTHS[int(b[5:]) - 1]} {b[:4]}"


def cash_flow_trend(figures: dict, client: dict) -> dict | None:
    by_month = figures["monthly_income"].detail.get("by_month", {})
    months = sorted(by_month)
    if len(months) < 6:
        return None
    recent, before = months[-3:], months[-6:-3]
    inc = lambda ms: sum(by_month[m]["value"] for m in ms)
    season = season_for(client["archetype"])
    expected = sum(season[int(m[5:])] for m in recent) / sum(season[int(m[5:])] for m in before) - 1
    actual = inc(recent) / inc(before) - 1 if inc(before) else 0.0
    gap = actual - expected
    verdict = ("in line with what the season predicts" if abs(gap) <= 0.10 else
               "better than the season predicts" if gap > 0 else "weaker than the season predicts")
    return {
        "recent": {"months": _span(recent), "income": round(inc(recent), 2),
                   "rows": [r for m in recent for r in by_month[m]["rows"]]},
        "before": {"months": _span(before), "income": round(inc(before), 2),
                   "rows": [r for m in before for r in by_month[m]["rows"]]},
        "change": round(actual, 4), "season_expects": round(expected, 4), "verdict": verdict,
        "text": (f"Business income in {_span(recent)} was {'up' if actual >= 0 else 'down'} "
                 f"{abs(actual):.0%} on {_span(before)}; the season predicts "
                 f"{'a rise' if expected >= 0 else 'a fall'} of {abs(expected):.0%}, so this is {verdict}."),
        "series": [{"month": m, "value": by_month[m]["value"]} for m in months],
    }


def suggested_products(figures: dict, findings: dict, client: dict, ledger: list[dict]) -> list[dict]:
    catalogue = json.loads(PRODUCTS_PATH.read_text("utf-8"))
    held = set(catalogue["held_by_everyone"])
    income = [r for r in ledger if r["direction"] == "credit"
              and r["category"] in ("customer_payment", "cash_deposit")]
    total = sum(r["amount"] for r in income) or 1.0
    cash = [r for r in income if r["category"] == "cash_deposit"]
    cash_share = sum(r["amount"] for r in cash) / total
    mm = figures["mobile_money_share"]
    out = []

    def suggest(key, why, figure=None, rows=None):
        if key not in held:
            p = catalogue["products"][key]
            out.append({"product": key, "name": p["name"], "what": p["what"], "why": why,
                        "figure": figure, "rows": rows if rows is not None else
                        (figures[figure].rows if figure else [])})

    if cash_share >= 0.25 or mm.value >= 0.3:
        suggest("merchant_collections",
                f"{cash_share:.0%} of income arrives as cash deposits and {mm.value:.0%} by mobile money.",
                rows=[r["row_id"] for r in cash] + mm.rows)
    if "seasonal_income" in findings:
        suggest("seasonal_savings",
                f"The peak month brings {figures['peak_to_median'].value:.1f} times a typical month's income.",
                "peak_month_income")
    if client["sector"] == "agriculture" or "drought_shock" in findings:
        suggest("crop_asset_insurance",
                "An agricultural business whose income depends on the harvest."
                + (" A drought shock already shows in the statements." if "drought_shock" in findings else ""),
                "harvest_ratio" if "harvest_ratio" in figures else None)
    if mm.value > 0.5:
        suggest("momo_repayments", f"{mm.value:.0%} of income is received by mobile money.",
                "mobile_money_share")
    return out


def open_issues(case: dict, ledger: list[dict]) -> list[dict]:
    issues = [{"kind": "escalation", "text": e["reason"], "stop": e["stop"]}
              for e in case.get("escalations", [])]
    review = [r["row_id"] for r in ledger if r.get("needs_review")]
    if review:
        issues.append({"kind": "review", "text": f"{len(review)} statement lines need review "
                       "(text that reads like instructions, or a label the model couldn't settle).",
                       "rows": review})
    unverified = [r["row_id"] for r in ledger if r["trust"] == "Unverified"]
    if unverified:
        issues.append({"kind": "unverified", "text": f"{len(unverified)} statement lines are "
                       "Unverified: they sit on an edited statement or a disputed transfer.",
                       "rows": unverified})
    if case.get("checks"):
        issues.append({"kind": "mocked", "text": "PACRA, ZRA and credit-bureau results come from "
                       "mocked services in this prototype; confirm them before deciding."})
    issues.append({"kind": "next", "text": NEXT_STEP.get(case["status"], "")})
    return issues


def risk_flags(findings: dict, figures: dict, score: dict | None) -> list[dict]:
    flags = [{"text": FINDING_TEXT[k], "figures": [e for e in v["evidence"] if e in figures]}
             for k, v in findings.items() if v["risk"]]
    for r in (score or {}).get("raises_risk", []):
        flags.append({"text": f"Raises the risk score: {r['text']}",
                      "figures": [r["figure"]] if r.get("figure") in figures else []})
    return flags


def build_brief(case: dict, ledger: list[dict], client: dict) -> dict:
    figures = {k: Figure(**v) for k, v in (case.get("figures") or {}).items()}
    if not figures:
        return {"available": False, "open_issues": open_issues(case, ledger)}
    findings = detect_findings(figures, client)
    return {
        "available": True,
        "trend": cash_flow_trend(figures, client),
        "products": suggested_products(figures, findings, client, ledger),
        "open_issues": open_issues(case, ledger),
        "risk_flags": risk_flags(findings, figures, case.get("score")),
        "context": [{"text": FINDING_TEXT[k], "figures": [e for e in v["evidence"] if e in figures]}
                    for k, v in findings.items() if not v["risk"]],
    }
