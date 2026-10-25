"""Tamper check, transfer cross-match and trust levels for a client's statements.

Trust levels, applied to every row:
- Verified: on the bank's own record (Absa), or a wallet transfer confirmed by the
  matching Absa row.
- Cross-checked: on a wallet statement whose balances reconcile end to end.
- Unverified: anything on a statement that fails reconciliation (an edited statement
  can't vouch for any of its rows), and any transfer that disagrees with Absa's record.
"""

from ..ledger import Statement

TOLERANCE = 0.01


def reconcile(statement: Statement) -> dict:
    """Every balance must equal the previous balance plus the row's amount."""
    breaks = []
    previous = statement.opening_balance
    for row in statement.rows:
        expected = round(previous + row.signed_amount, 2)
        if abs(expected - row.balance) > TOLERANCE:
            breaks.append({
                "row_id": row.row_id,
                "shown_amount": row.amount,
                "implied_amount": round(abs(row.balance - previous), 2),
                "expected_balance": expected,
                "shown_balance": row.balance,
            })
        previous = row.balance
    closing_matches = abs(previous - statement.closing_balance) <= TOLERANCE
    return {
        "statement_id": statement.statement_id,
        "rows": len(statement.rows),
        "reconciles": not breaks and closing_matches,
        "closing_matches": closing_matches,
        "breaks": breaks,
    }


def _covers(statement: Statement, day: str) -> bool:
    """Whether a statement's period includes this date; statements often cover different spans."""
    return bool(statement.rows) and statement.rows[0].date <= day <= statement.rows[-1].date


def cross_match(absa: Statement, wallets: list[Statement]) -> dict:
    """Pair wallet-to-bank transfers with Absa's record of them, by reference.

    A transfer only lacks a partner if the other statement covers its date.
    """
    absa_by_ref = {r.reference: r for r in absa.rows}
    matched, mismatched, unmatched = [], [], []
    wallet_refs = set()
    for wallet in wallets:
        for row in wallet.rows:
            wallet_refs.add(row.reference)
            bank_row = absa_by_ref.get(row.reference)
            if bank_row is None:
                if (row.direction == "debit" and "BANK ABSA" in row.description.upper()
                        and _covers(absa, row.date)):
                    unmatched.append(row.row_id)
                continue
            if (abs(bank_row.amount - row.amount) <= TOLERANCE
                    and bank_row.direction != row.direction):
                matched.append([row.row_id, bank_row.row_id])
            else:
                mismatched.append({"wallet_row": row.row_id, "absa_row": bank_row.row_id,
                                   "wallet_amount": row.amount, "absa_amount": bank_row.amount})
    # Absa credits that name a supplied wallet but have no partner on its statement.
    for row in absa.rows:
        wallet = next((w for w in wallets if w.account in row.description), None)
        if (wallet and "MOMO TRF" in row.description and row.reference not in wallet_refs
                and _covers(wallet, row.date)):
            unmatched.append(row.row_id)
    return {"matched": matched, "mismatched": mismatched, "unmatched": unmatched}


def verify_case(statements: list[Statement]) -> dict:
    """Run every check on one client's statements and set each row's trust level."""
    checks = {s.statement_id: reconcile(s) for s in statements}
    absa = next((s for s in statements if s.channel == "absa"), None)
    wallets = [s for s in statements if s.channel != "absa"]
    transfers = (cross_match(absa, wallets) if absa and wallets
                 else {"matched": [], "mismatched": [], "unmatched": []})

    confirmed = {row_id for pair in transfers["matched"] for row_id in pair}
    disputed = {m["wallet_row"] for m in transfers["mismatched"]}
    disputed |= {m["absa_row"] for m in transfers["mismatched"]}
    disputed |= set(transfers["unmatched"])
    for s in statements:
        clean = checks[s.statement_id]["reconciles"]
        for row in s.rows:
            if row.row_id in disputed:
                row.trust = "Unverified"
            elif row.row_id in confirmed and clean:
                row.trust = "Verified"
            elif not clean:
                row.trust = "Unverified"
            else:
                row.trust = "Verified" if s.channel == "absa" else "Cross-checked"

    flagged = sorted({b["row_id"] for c in checks.values() for b in c["breaks"]} | disputed)
    return {
        "statements": list(checks.values()),
        "transfers": transfers,
        "flagged_rows": flagged,
        "passed": not flagged and all(c["reconciles"] for c in checks.values()),
    }
