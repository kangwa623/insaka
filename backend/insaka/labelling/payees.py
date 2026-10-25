"""Payment history per counterparty, computed in code and handed to the model as evidence.

Wages, rent and money for relatives can look identical on a single row ("Sent to
PERSON_04"). Their history differs: wages and rent are the same amount every month at
the same time of month, family support varies.
"""

import re
from collections import defaultdict

from ..ledger import Statement

_PERSON = re.compile(r"PERSON_\d+(\[owner-surname\])?")
_SENT_TO = re.compile(r"^(?:Money )?[Ss]ent to (?:\[phone\] )?(?P<payee>.+)$")


def payee_key(masked_description: str) -> str | None:
    """The counterparty a row is about, if the description names one."""
    m = _PERSON.search(masked_description)
    if m:
        return m.group(0)
    m = _SENT_TO.match(masked_description)
    return m.group("payee") if m else None


def summarise_payees(statements: list[Statement], masked: dict) -> dict:
    """One line of history per counterparty that money was sent to."""
    months = {row.date[:7] for s in statements for row in s.rows}
    paid = defaultdict(list)
    for s in statements:
        for row in s.rows:
            key = payee_key(masked[row.row_id])
            if key and row.direction == "debit":
                paid[key].append(row)
    summaries = {}
    for key, rows in paid.items():
        amounts = sorted({r.amount for r in rows})
        days = sorted(int(r.date[8:]) for r in rows)
        paid_months = len({r.date[:7] for r in rows})
        amount = (f"always K{amounts[0]:,.2f}" if len(amounts) == 1
                  else f"varies K{amounts[0]:,.2f}-K{amounts[-1]:,.2f}")
        summaries[key] = (f"paid {len(rows)} times in {paid_months} of {len(months)} months, "
                          f"{amount}, on days {days[0]}-{days[-1]} of the month")
    return summaries
