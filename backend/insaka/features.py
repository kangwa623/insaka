"""Cash-flow features from a labelled ledger, each traceable to the rows it came from.

Every number the memo shows is a Figure: a value plus the row_ids that produced it, so
the RM can click any figure and see its source transactions. Code computes all of them;
no language model touches a number.

Seasonality is measured, not punished: volatility is also computed after dividing out
the business's expected Zambian season (harvest, input sales, festive retail...).
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np

from .generator.archetypes import BY_KEY, MWILA_ARCHETYPE
from .generator.profiles import instalment
from .generator.seasons import SEASONAL
from .labelling.masking import PHONE
from .ledger import Statement
from .taxonomy import INCOME_CATEGORIES

COMMITTED_CATEGORIES = ("input_purchase", "rent", "wages", "loan_repayment")

_LEAD = re.compile(r"^(?:Money )?(?:[Rr]eceived from|EFT CR|TRF FROM)\s+(?:\[phone\]\s+)?")


@dataclass
class Figure:
    name: str
    label: str
    value: float | str
    unit: str                      # "K", "%", "x", "month" (value "2026-05") or ""
    rows: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def season_for(archetype: str) -> dict:
    a = MWILA_ARCHETYPE if archetype == MWILA_ARCHETYPE.key else BY_KEY[archetype]
    return SEASONAL[a.season]


def _months(rows) -> list[str]:
    first, last = min(r.date[:7] for r in rows), max(r.date[:7] for r in rows)
    y, m = int(first[:4]), int(first[5:])
    months = []
    while f"{y}-{m:02d}" <= last:
        months.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def _customer_names(rows) -> dict:
    """row_id -> customer name for customer payments.

    Features stay in code and never reach the model, so real names are used here.
    "TRF FROM BANDA C" is matched to the one full name with that surname and initial.
    """
    raw = {r.row_id: _LEAD.sub("", PHONE.sub("", r.description)).strip() for r in rows}
    full = {}
    for name in raw.values():
        words = name.split()
        if len(words) >= 2 and len(words[-1]) > 1:
            full.setdefault((words[-1], words[0][0]), set()).add(name)
    names = {}
    for row_id, name in raw.items():
        words = name.split()
        if len(words) == 2 and len(words[1]) == 1:
            matches = full.get((words[0], words[1]), set())
            name = next(iter(matches)) if len(matches) == 1 else name
        names[row_id] = name
    return names


def overdraft_days(absa: Statement, months: list[str]) -> tuple[int, int, list]:
    """Days the Absa account closed below zero, days in the window, and the rows that did it."""
    day = date(int(months[0][:4]), int(months[0][5:]), 1)
    y, m = int(months[-1][:4]), int(months[-1][5:])
    end = date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)
    rows = absa.rows
    balance, i, negative, total, culprits = absa.opening_balance, 0, 0, 0, set()
    last_row = None
    while day <= end:
        while i < len(rows) and date.fromisoformat(rows[i].date) <= day:
            balance, last_row = rows[i].balance, rows[i].row_id
            i += 1
        if balance < 0:
            negative += 1
            if last_row:
                culprits.add(last_row)
        total += 1
        day += timedelta(days=1)
    return negative, total, sorted(culprits)


def compute_features(statements: list[Statement], client: dict,
                     corrections: dict | None = None) -> dict[str, Figure]:
    """Features for one client from labelled statements.

    client is the application record (clients.json). corrections maps row_id to the amount
    the balances imply, for rows the tamper check caught: the bank's running balance is
    trusted over an edited amount.
    """
    corrections = corrections or {}
    rows = [r for s in statements for r in s.rows]
    months = _months(rows)
    season = season_for(client["archetype"])
    customer_of = _customer_names([r for r in rows if r.category == "customer_payment"
                                   and r.direction == "credit"])

    def amount(r):
        return corrections.get(r.row_id, r.amount)

    income = {k: 0.0 for k in months}
    income_rows = {k: [] for k in months}
    committed = {k: 0.0 for k in months}
    committed_rows = []
    customers, customer_rows = {}, {}
    wallet_income, wallet_rows = 0.0, []
    for r in rows:
        k = r.date[:7]
        if r.category in INCOME_CATEGORIES and r.direction == "credit":
            income[k] += amount(r)
            income_rows[k].append(r.row_id)
            if r.channel != "absa":
                wallet_income += amount(r)
                wallet_rows.append(r.row_id)
        if r.category == "customer_payment" and r.direction == "credit":
            key = customer_of[r.row_id]
            customers[key] = customers.get(key, 0.0) + amount(r)
            customer_rows.setdefault(key, []).append(r.row_id)
        if r.category in COMMITTED_CATEGORIES and r.direction == "debit":
            committed[k] += amount(r)
            committed_rows.append(r.row_id)

    raw = np.array([income[k] for k in months])
    deseasoned = np.array([income[k] / season[int(k[5:])] for k in months])
    all_income_rows = [x for k in months for x in income_rows[k]]
    surplus = float(np.mean([income[k] - committed[k] for k in months]))
    app = client["application"]
    new_instalment = instalment(app["requested_amount"], app["tenor_months"])
    peak = max(months, key=lambda k: income[k])
    total_income = float(raw.sum())
    top = max(customers, key=customers.get) if customers else None
    customer_total = sum(customers.values())
    absa = next((s for s in statements if s.channel == "absa"), None)
    od_days, window_days, od_rows = overdraft_days(absa, months) if absa else (0, 1, [])
    unverified = [r.row_id for r in rows if r.row_id in set(all_income_rows)
                  and r.trust == "Unverified"]

    def cv(x):
        return float(x.std() / x.mean()) if x.mean() > 0 else 0.0

    figures = [
        Figure("months", "Months of statement history", len(months), "",
               [r.row_id for r in rows], {"from": months[0], "to": months[-1]}),
        Figure("mean_monthly_income", "Average monthly business income", float(raw.mean()), "K",
               all_income_rows),
        Figure("monthly_income", "Business income by month", total_income, "K", all_income_rows,
               {"by_month": {k: {"value": round(income[k], 2), "rows": income_rows[k]}
                             for k in months}}),
        Figure("raw_income_cv", "Month-to-month income variation", cv(raw), "%", all_income_rows),
        Figure("deseasoned_income_cv", "Income variation after allowing for the season",
               cv(deseasoned), "%", all_income_rows),
        Figure("peak_month", "The month with the most income", peak, "month", income_rows[peak]),
        Figure("peak_month_income", "Income in the peak month", income[peak], "K",
               income_rows[peak], {"month": peak}),
        Figure("peak_to_median", "Peak month compared with a typical month",
               float(raw.max() / np.median(raw)) if np.median(raw) > 0 else 0.0, "x",
               income_rows[peak]),
        # A zero rests on every row checked, so it links to all of them.
        Figure("overdraft_day_share", "Share of days the Absa account was overdrawn",
               od_days / window_days, "%",
               od_rows or ([r.row_id for r in absa.rows] if absa else []),
               {"days": od_days, "of": window_days}),
        Figure("top_customer_share", "Share of customer payments from the largest customer",
               customers[top] / customer_total if top else 0.0, "%",
               customer_rows.get(top, []), {"customer": top}),
        Figure("mobile_money_share", "Share of income received by mobile money",
               wallet_income / total_income if total_income else 0.0, "%", wallet_rows),
        Figure("mean_monthly_committed", "Average monthly supplier, rent, wages and loan payments",
               float(np.mean([committed[k] for k in months])), "K", committed_rows),
        Figure("mean_monthly_surplus", "Average monthly surplus after committed costs", surplus,
               "K", all_income_rows + committed_rows),
        Figure("new_instalment", "Monthly instalment on the requested loan", new_instalment, "K",
               [], {"amount": app["requested_amount"], "tenor_months": app["tenor_months"],
                    "source": "application"}),
        Figure("debt_service_coverage", "Surplus cover for the new instalment",
               surplus / new_instalment, "x", all_income_rows + committed_rows),
        Figure("unverified_income_share", "Share of income on unverified rows",
               sum(amount(r) for r in rows if r.row_id in set(unverified)) / total_income
               if total_income else 0.0, "%", unverified or all_income_rows),
    ]
    return {f.name: f for f in figures}
