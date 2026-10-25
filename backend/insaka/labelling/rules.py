"""Keyword rules: the baseline the language model is measured against, and its fallback.

Each rule matches the description formats the statements print. Plain transfers to a
person ("Sent to ...", "TRF TO ...") are all called family transfers: telling wages and
rent apart from family needs the payment history, which is the model's job.
"""

import re

from ..ledger import LedgerRow

WALLETS = ("mtn", "airtel")

# (rule_id, channels, direction, pattern, category); the first match wins.
RULES = [
    ("absa.momo_trf", ("absa",), "credit", r"\b(MTN|AIRTEL) MOMO TRF\b", "own_account_transfer"),
    ("absa.eft_cr", ("absa",), "credit", r"^EFT CR\b", "customer_payment"),
    ("absa.trf_from", ("absa",), "credit", r"^TRF FROM\b", "customer_payment"),
    ("absa.cash_deposit", ("absa",), "credit", r"^CASH DEPOSIT\b", "cash_deposit"),
    ("absa.eft_dr", ("absa",), "debit", r"^EFT DR\b", "input_purchase"),
    ("absa.trf_to", ("absa",), "debit", r"^TRF TO\b", "family_transfer"),
    ("absa.atm", ("absa",), "debit", r"^ATM WDL\b", "cash_withdrawal"),
    ("absa.rent", ("absa",), "debit", r"^STANDING ORDER RENT\b", "rent"),
    ("absa.salary", ("absa",), "debit", r"^SALARY\b", "wages"),
    ("absa.school_fees", ("absa",), "debit", r"^SCHOOL FEES\b", "school_fees"),
    ("absa.loan", ("absa",), "debit", r"^LOAN REPAYMENT\b", "loan_repayment"),
    ("absa.zra", ("absa",), "debit", r"^ZRA PAYMENT\b", "tax_payment"),
    ("absa.fees", ("absa",), "debit",
     r"^(MONTHLY SERVICE FEE|SMS ALERT FEE|OVERDRAFT INTEREST)\b", "bank_charges"),
    ("absa.zesco", ("absa",), "debit", r"^ZESCO\b", "utilities"),
    ("absa.airtime", ("absa",), "debit", r"^AIRTIME PURCHASE\b", "airtime_data"),
    ("wallet.received", WALLETS, "credit", r"^(Money )?[Rr]eceived from\b", "customer_payment"),
    ("wallet.cash_in", WALLETS, "credit", r"^Cash In\b", "cash_deposit"),
    ("wallet.cash_out_fee", WALLETS, "debit", r"^Cash Out Fee\b", "bank_charges"),
    ("wallet.cash_out", WALLETS, "debit", r"^Cash Out\b", "cash_withdrawal"),
    ("wallet.to_bank", WALLETS, "debit", r"^Transfer to Bank\b", "own_account_transfer"),
    ("wallet.merchant", WALLETS, "debit", r"^(Merchant Payment|Pay Merchant)\b", "input_purchase"),
    ("wallet.zesco", WALLETS, "debit", r"^ZESCO Token\b", "utilities"),
    ("wallet.airtime", WALLETS, "debit", r"^(Airtime Purchase|Data Bundle)\b", "airtime_data"),
    ("wallet.loan", WALLETS, "debit", r"^Loan Repayment\b", "loan_repayment"),
    ("wallet.school", WALLETS, "debit", r"^Payment to .*\b(School|Academy|College)\b",
     "school_fees"),
    ("wallet.sent_to", WALLETS, "debit", r"^(Money )?[Ss]ent to\b", "family_transfer"),
]

_COMPILED = [(rule_id, channels, direction, re.compile(pattern), category)
             for rule_id, channels, direction, pattern, category in RULES]


def rule_label(row: LedgerRow) -> tuple[str, str, str]:
    """(category, rule_id, quote) for one row; ("other", "fallback.none", "") if no rule fits."""
    for rule_id, channels, direction, pattern, category in _COMPILED:
        if row.channel in channels and row.direction == direction:
            m = pattern.search(row.description)
            if m:
                return category, rule_id, m.group(0)
    return "other", "fallback.none", ""
