"""The agent's tools: thin wrappers over the pipeline, each returning a short summary.

A tool keeps its full result on the AgentCase (for the memo, the UI and the audit) and
hands the model only a compact, masked summary: no names, no transaction rows. There is
no tool to approve, decline or disburse a loan; people do that (see insaka.case).
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..evaluation.labelling import load_statement
from ..features import _months
from ..labelling import label_case
from ..memo import assess, draft, save
from ..parsing import parse_statement, verify_case
from . import mocks

ESCALATION_KINDS = ("spot_check", "registration", "suspicious_text", "thin_history", "other")
MIN_MONTHS = 6


class NoChat:
    """Forces the template memo (tests, and when the model must not be called)."""

    model = "none"

    def __call__(self, system, user):
        raise RuntimeError("no language model in this run")


@dataclass
class AgentCase:
    client: dict
    sources: dict                       # channel -> callable returning a Statement
    registry: dict = field(default_factory=mocks.load_registry)
    label_method: str = "llm"           # "llm" (cache first, rules if unavailable) or "rules"
    memo_chat: object = None            # None: Qwen on Groq; NoChat(): template only
    memo_dir: str | Path = "data/memos"    # Qwen draft cache
    memo_out: str | Path = "data/cases"    # the rendered memo, beside the case file
    available: set = field(default_factory=lambda: {"absa"})
    requested: list = field(default_factory=list)
    statements: dict = field(default_factory=dict)
    report: dict | None = None
    labelling: dict | None = None
    checks: dict = field(default_factory=dict)
    assessment: dict | None = None
    memo: dict | None = None
    escalations: list = field(default_factory=list)
    status: str = "preparing"
    finished: bool = False

    @property
    def client_id(self) -> str:
        return self.client["client_id"]

    @property
    def wallets_listed(self) -> list[str]:
        return [c for c in self.client["channels"] if c != "absa"]

    def months_covered(self) -> int:
        rows = [r for s in self.statements.values() for r in s.rows]
        return len(_months(rows)) if rows else 0

    def ordered_statements(self) -> list:
        return [self.statements[c] for c in ("absa", "mtn", "airtel") if c in self.statements]

    def reset_downstream(self) -> None:
        """New evidence invalidates everything computed from the old evidence."""
        self.report = self.labelling = self.assessment = self.memo = None


# --- statement sources ---------------------------------------------------------------

def pdf_sources(client: dict, statements_dir: str | Path) -> dict:
    d = Path(statements_dir)
    return {ch: (lambda p=d / f"{client['client_id']}_{ch}.pdf": parse_statement(p))
            for ch in client["channels"]}


def csv_sources(data_dir: str | Path, client: dict, truth: dict, absa_months: int | None = None) -> dict:
    """Statements from the ground-truth CSVs; absa_months keeps only the last N Absa months."""
    def load(channel):
        statement, _ = load_statement(Path(data_dir), client, channel)
        statement.opening_balance = truth["opening_balances"][channel]
        if channel == "absa" and absa_months:
            keep = set(_months(statement.rows)[-absa_months:])
            dropped = [r for r in statement.rows if r.date[:7] not in keep]
            statement.rows = [r for r in statement.rows if r.date[:7] in keep]
            if dropped:
                statement.opening_balance = dropped[-1].balance
        statement.closing_balance = (statement.rows[-1].balance if statement.rows
                                     else statement.opening_balance)
        return statement
    return {ch: (lambda c=ch: load(c)) for ch in client["channels"]}


# --- tools ---------------------------------------------------------------------------

def read_statement(case: AgentCase, channel: str) -> dict:
    statement = case.sources[channel]()
    case.statements[channel] = statement
    case.reset_downstream()
    rows = statement.rows
    return {"channel": channel, "rows": len(rows),
            "from": rows[0].date if rows else None, "to": rows[-1].date if rows else None,
            "months_covered_by_all_statements_read": case.months_covered(),
            "listed_wallets_not_yet_requested": [w for w in case.wallets_listed
                                                 if w not in case.requested]}


def request_documents(case: AgentCase, channels: list) -> dict:
    token = hashlib.sha256(f"{case.client_id}:{sorted(channels)}".encode()).hexdigest()[:12]
    case.requested += [c for c in channels if c not in case.requested]
    case.available |= set(channels)
    return {"requested": channels, "simulated": True,
            "upload_link": f"https://insaka.example/upload/{token}",
            "consent_screen_shown": True,
            "note": "In the prototype the customer uploads at once; read the statements next."}


def verify_statements(case: AgentCase) -> dict:
    case.report = verify_case(case.ordered_statements())
    r = case.report
    return {"passed": r["passed"],
            "statements": [{"statement": s["statement_id"], "reconciles": s["reconciles"],
                            "balance_breaks": len(s["breaks"])} for s in r["statements"]],
            "transfers_matched": len(r["transfers"]["matched"]),
            "transfers_disagreeing": len(r["transfers"]["mismatched"]),
            "transfers_without_partner": len(r["transfers"]["unmatched"]),
            "flagged_rows": len(r["flagged_rows"])}


def label_transactions(case: AgentCase) -> dict:
    statements = case.ordered_statements()
    fell_back = None
    if case.label_method == "llm":
        try:
            case.labelling = label_case(statements, "llm")
        except Exception as e:   # no key, daily quota spent: the rules still label every row
            fell_back = type(e).__name__
            case.labelling = label_case(statements, "rules")
    else:
        case.labelling = label_case(statements, "rules")
    s = case.labelling
    top = sorted(s["categories"].items(), key=lambda kv: -kv[1])[:6]
    return {"rows": s["rows"], "labelled_by": s.get("model", "keyword rules"),
            "fell_back_to_rules_because": fell_back, "top_categories": dict(top),
            "rows_needing_review": len(s["needs_review"]),
            "rows_with_text_that_reads_like_instructions": len(s["injection_suspected"])}


def _check(case: AgentCase, key: str, lookup) -> dict:
    result = lookup(case.client, case.registry)
    case.checks[key] = result
    return {k: v for k, v in result.items() if k not in ("business_name",)}


def check_registration(case: AgentCase) -> dict:
    return _check(case, "pacra", mocks.pacra_lookup)


def check_tax_status(case: AgentCase) -> dict:
    return _check(case, "zra", mocks.zra_lookup)


def check_credit_bureau(case: AgentCase) -> dict:
    return _check(case, "bureau", mocks.bureau_lookup)


def score_risk(case: AgentCase) -> dict:
    case.assessment = assess(case.ordered_statements(), case.report, case.client,
                             checks=case.checks)
    a = case.assessment
    s = a["score"]
    return {"probability_of_default": round(s["pd"], 3), "risk_band": s["band"],
            "findings": {k: "risk" if v["risk"] else "context" for k, v in a["findings"].items()},
            "raises_risk": [r["text"] for r in s["raises_risk"]],
            "lowers_risk": [r["text"] for r in s["lowers_risk"]]}


def draft_memo(case: AgentCase) -> dict:
    case.memo = draft(case.assessment, case.labelling or {}, chat=case.memo_chat,
                      cache_dir=case.memo_dir)
    save(case.memo, case.assessment, case.memo_out)
    m = case.memo
    return {"written_by": m["written_by"], "figures_used": m["figures_used"],
            "figures_linked_to_source": m["figures_linked"],
            "numbers_without_source": m["unsupported_numbers"]}


def escalate(case: AgentCase, kind: str, stop: bool = False, reason: str = "") -> dict:
    case.escalations.append({"kind": kind, "stop": bool(stop), "reason": reason})
    if stop:
        case.status, case.finished = "escalated", True
    return {"recorded": True, "kind": kind, "case_stopped": bool(stop)}


def submit_for_review(case: AgentCase) -> dict:
    case.status, case.finished = "awaiting_rm", True
    return {"status": "Awaiting RM review",
            "note": "The RM reviews and edits the memo; an approver decides."}


def _schema(name, description, properties=None, required=()):
    props = {"reason": {"type": "string", "description": "Why you are calling this, for the RM"}}
    props.update(properties or {})
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props,
                       "required": ["reason", *required]}}}


CHANNEL = {"type": "string", "enum": ["absa", "mtn", "airtel"]}

TOOLS = {
    "read_statement": (read_statement, _schema(
        "read_statement", "Parse one statement that is available into the standard ledger.",
        {"channel": CHANNEL}, ["channel"])),
    "request_documents": (request_documents, _schema(
        "request_documents", "Send the customer a secure upload link (with a consent screen) "
        "for mobile-money statements they listed on the application.",
        {"channels": {"type": "array", "items": {"type": "string", "enum": ["mtn", "airtel"]}}},
        ["channels"])),
    "verify_statements": (verify_statements, _schema(
        "verify_statements", "Run the tamper check on every statement read and cross-match "
        "wallet-to-bank transfers with Absa's records.")),
    "label_transactions": (label_transactions, _schema(
        "label_transactions", "Label every transaction with a category, quoting its source row.")),
    "check_registration": (check_registration, _schema(
        "check_registration", "Confirm the business with PACRA (mocked in the prototype).")),
    "check_tax_status": (check_tax_status, _schema(
        "check_tax_status", "Confirm TPIN and tax compliance with ZRA (mocked).")),
    "check_credit_bureau": (check_credit_bureau, _schema(
        "check_credit_bureau", "Run the mandatory credit-bureau check (mocked).")),
    "score_risk": (score_risk, _schema(
        "score_risk", "Compute the cash-flow features, findings and the risk score.")),
    "draft_memo": (draft_memo, _schema(
        "draft_memo", "Draft the credit memo; code inserts and links every figure.")),
    "escalate": (escalate, _schema(
        "escalate", "Flag an issue for the RM. stop=true ends the case here for a person.",
        {"kind": {"type": "string", "enum": list(ESCALATION_KINDS)},
         "stop": {"type": "boolean"}}, ["kind"])),
    "submit_for_review": (submit_for_review, _schema(
        "submit_for_review", "Hand the finished case to the RM for review.")),
}

TOOL_SCHEMAS = [schema for _, schema in TOOLS.values()]


def tool_summary_text(result: dict) -> str:
    return f"<tool_result>{json.dumps(result, default=str)}</tool_result>"
