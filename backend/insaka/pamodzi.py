"""Pamodzi ("together"): bank and wallet flows combined into one monthly picture.

Every amount carries the rows it was added up from. Money moved between the owner's own
accounts (Absa <-> MoMo) is shown on its own and left out of the combined money in and
out, so it isn't counted twice. Each channel's month is checked: money in minus money out
must equal the change in its balance; an edited statement shows up as a mismatch.
"""

from collections import defaultdict

OWN = "own_account_transfer"
TOLERANCE = 0.01


def _signed(r: dict) -> float:
    return r["amount"] if r["direction"] == "credit" else -r["amount"]


def monthly_flows(ledger: list[dict]) -> dict:
    by_channel = defaultdict(list)
    for r in ledger:
        by_channel[r["channel"]].append(r)
    months = sorted({r["date"][:7] for r in ledger})
    channels = [c for c in ("absa", "mtn", "airtel") if c in by_channel]

    cells = {m: {c: {"in": 0.0, "out": 0.0, "own_in": 0.0, "own_out": 0.0, "rows_in": [],
                     "rows_out": [], "rows_own": [], "end_balance": None, "start_balance": None}
                 for c in channels} for m in months}
    mismatches = []
    for c in channels:
        rows = by_channel[c]
        previous = rows[0]["balance"] - _signed(rows[0]) if rows else 0.0
        for m in months:
            cells[m][c]["start_balance"] = round(previous, 2)
        for r in rows:
            cell = cells[r["date"][:7]][c]
            if cell["end_balance"] is None:
                cell["start_balance"] = round(previous, 2)
            own = r["category"] == OWN
            if r["direction"] == "credit":
                cell["own_in" if own else "in"] += r["amount"]
            else:
                cell["own_out" if own else "out"] += r["amount"]
            cell["rows_own" if own else "rows_in" if r["direction"] == "credit" else "rows_out"].append(r["row_id"])
            cell["end_balance"] = r["balance"]
            previous = r["balance"]
        carried = None
        for m in months:
            cell = cells[m][c]
            if cell["end_balance"] is None:   # a month with no rows keeps the balance it had
                cell["end_balance"] = carried if carried is not None else cell["start_balance"]
            carried = cell["end_balance"]
            moved = cell["in"] - cell["out"] + cell["own_in"] - cell["own_out"]
            change = cell["end_balance"] - cell["start_balance"]
            if abs(moved - change) > TOLERANCE:
                mismatches.append({"month": m, "channel": c, "flows": round(moved, 2),
                                   "balance_change": round(change, 2)})

    out_months = []
    for m in months:
        row = {"month": m, "channels": {}}
        tin = tout = town = 0.0
        rows_in, rows_out, rows_own = [], [], []
        for c in channels:
            cell = cells[m][c]
            row["channels"][c] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in cell.items()}
            tin += cell["in"]
            tout += cell["out"]
            town += cell["own_out"]
            rows_in += cell["rows_in"]
            rows_out += cell["rows_out"]
            rows_own += cell["rows_own"]
        row.update({"in": round(tin, 2), "out": round(tout, 2), "net": round(tin - tout, 2),
                    "moved_between_own_accounts": round(town, 2),
                    "rows_in": rows_in, "rows_out": rows_out, "rows_own": rows_own})
        out_months.append(row)

    total_in = sum(m["in"] for m in out_months)
    return {
        "channels": channels,
        "months": out_months,
        "totals": {
            "in": round(total_in, 2),
            "out": round(sum(m["out"] for m in out_months), 2),
            "net": round(sum(m["net"] for m in out_months), 2),
            "average_monthly_net": round(sum(m["net"] for m in out_months) / len(out_months), 2)
            if out_months else 0.0,
            "moved_between_own_accounts": round(sum(m["moved_between_own_accounts"] for m in out_months), 2),
            "share_in_by_channel": {c: round(sum(m["channels"][c]["in"] for m in out_months) / total_in, 4)
                                    if total_in else 0.0 for c in channels},
            "rows_in": [x for m in out_months for x in m["rows_in"]],
            "rows_out": [x for m in out_months for x in m["rows_out"]],
            "rows_own": [x for m in out_months for x in m["rows_own"]],
        },
        "balance_check": {"months_checked": len(months) * len(channels), "mismatches": mismatches},
    }
