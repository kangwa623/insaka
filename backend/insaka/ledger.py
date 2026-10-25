"""The standard ledger: every statement, whatever its source, becomes these rows."""

from dataclasses import asdict, dataclass, field

TRUST_LEVELS = ("Verified", "Cross-checked", "Unverified")


@dataclass
class LedgerRow:
    row_id: str          # "{statement_id}-{n:04d}", stable for tracing figures back
    channel: str         # "absa", "mtn" or "airtel"
    date: str            # ISO yyyy-mm-dd
    time: str            # HH:MM:SS where the statement prints it, else ""
    description: str
    reference: str
    direction: str       # "credit" or "debit"
    amount: float        # always positive; direction carries the sign
    balance: float
    page: int
    trust: str = ""      # set by verify.verify_case

    @property
    def signed_amount(self) -> float:
        return self.amount if self.direction == "credit" else -self.amount


@dataclass
class Statement:
    statement_id: str    # e.g. "MWILA-001-ABSA"
    channel: str
    holder: str
    business: str
    account: str
    period: str
    opening_balance: float
    closing_balance: float
    source_file: str
    rows: list[LedgerRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
