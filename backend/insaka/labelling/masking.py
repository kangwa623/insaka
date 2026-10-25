"""Mask personal details before any statement text reaches a language model.

Phone numbers become "[phone]". People become stable tokens per client (PERSON_07), so
the model can still see that the same person is paid every month. A person who shares
the account holder's surname is marked PERSON_07[owner-surname]: relatives usually do,
and that cue matters for labelling. Business names stay: they carry the meaning of the
payment and aren't personal data.
"""

import re
from dataclasses import dataclass, field

from ..ledger import Statement

PHONE = re.compile(r"\b\d{3}\*{4}\d{2,4}\b")

# Words that mark a counterparty as an organisation rather than a person.
BUSINESS_WORDS = {
    "LTD", "LIMITED", "PLC", "CO", "COMPANY", "ENTERPRISES", "TRADING", "WHOLESALE",
    "WHOLESALERS", "SUPPLIES", "SUPPLIERS", "DISTRIBUTORS", "DEPOT", "STORES", "SHOP",
    "MARKET", "SUPERMARKET", "LODGE", "HOTEL", "FOODS", "MILLERS", "KITCHEN", "SCHOOL",
    "SCHOOLS", "ACADEMY", "COLLEGE", "PROPERTIES", "ESTATES", "RENTALS", "COUNCIL",
    "MICROFINANCE", "CREDIT", "LENDING", "BANK", "MOTORS", "STATION", "HOUSE", "ZAMBIA",
}

# Where a person's name sits in each description format.
_FULL_NAME = re.compile(
    r"^(?P<lead>(?:Money )?(?:[Rr]eceived from|[Ss]ent to) (?:\[phone\] )?|EFT CR |SALARY )"
    r"(?P<name>[A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)+)$")
_SURNAME_INITIAL = re.compile(r"^(?P<lead>TRF (?:FROM|TO) )(?P<surname>[A-Z'\-]+) (?P<initial>[A-Z])$")


@dataclass
class Masker:
    holder_surname: str
    tokens: dict = field(default_factory=dict)    # (surname, initial) -> token
    names: dict = field(default_factory=dict)     # token -> names seen

    def _token(self, surname: str, first: str, shown: str) -> str:
        key = (surname.upper(), first[0].upper())
        if key not in self.tokens:
            token = f"PERSON_{len(self.tokens) + 1:02d}"
            if key[0] == self.holder_surname.upper():
                token += "[owner-surname]"
            self.tokens[key] = token
        token = self.tokens[key]
        self.names.setdefault(token, set()).add(shown)
        return token

    def mask(self, description: str) -> str:
        text = PHONE.sub("[phone]", description)
        m = _FULL_NAME.match(text)
        if m:
            words = m.group("name").split()
            if len(words) <= 3 and not BUSINESS_WORDS & set(words):
                return m.group("lead") + self._token(words[-1], words[0], m.group("name"))
            return text
        m = _SURNAME_INITIAL.match(text)
        if m:
            shown = f"{m.group('surname')} {m.group('initial')}"
            return m.group("lead") + self._token(m.group("surname"), m.group("initial"), shown)
        return text


def own_accounts(statements: list[Statement]) -> dict:
    """The client's own account numbers, so transfers between them read as such."""
    return {s.account: f"[own {'Absa account' if s.channel == 'absa' else s.channel.upper() + ' wallet'}]"
            for s in statements if s.account}


def mask_case(statements: list[Statement]) -> tuple[dict, dict]:
    """Masked description per row_id, and each token's real names (for the UI only)."""
    holder = statements[0].holder if statements else ""
    masker = Masker(holder.split()[-1] if holder else "")
    own = own_accounts(statements)
    masked = {}
    for s in statements:
        for row in s.rows:
            text = row.description
            for account, label in own.items():
                text = text.replace(account, label)
            masked[row.row_id] = masker.mask(text)
    return masked, {t: sorted(n) for t, n in masker.names.items()}
