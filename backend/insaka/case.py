"""The case after the agent: people review, decide and pay out, and every action is logged.

    preparing -> awaiting_rm -> submitted -> approved | declined -> disbursed
                 escalated (the agent stopped, or a person escalated; another person resolves)

Roles are checked here, on the server side, not in the screens:
- the RM the case is assigned to (or a manager) edits the memo and submits the case;
- an approver decides within their delegated limit, and never on a case they submitted
  (maker-checker); a High-risk case needs a resolved credit-risk escalation first;
- anyone working the case can escalate it (credit risk, compliance, fraud); someone else,
  with approval authority, resolves it;
- money moves only after a recorded approval, through the MoMo sandbox (mocked);
- an auditor can read everything and change nothing.
Each action is appended to {client}.audit.jsonl; nothing in the audit log is rewritten.
"""

import hashlib
import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .security import atomic_write

CASES_DIR = Path("data/cases")

# Synthetic staff for the prototype. The manager holds every working role, to show
# maker-checker: even they cannot decide a case they submitted.
USERS = {
    "rm.chanda": {"name": "Chanda M.", "roles": ["rm"]},
    "rm.mutale": {"name": "Mutale K.", "roles": ["rm"]},
    "approver.banda": {"name": "Banda S.", "roles": ["approver"]},
    "manager.zulu": {"name": "Zulu T.", "roles": ["rm", "approver", "manager"]},
    "auditor.phiri": {"name": "Phiri N.", "roles": ["auditor"]},
}

# Delegated credit authority, in kwacha (the brief: approvers decide within their limits).
APPROVAL_LIMITS = {"approver.banda": 500_000, "manager.zulu": 1_000_000}
DEFAULT_RM = "rm.chanda"
ESCALATE_TO = {"credit_risk": "Credit risk", "compliance": "Compliance", "fraud": "Fraud"}
MAX_NOTE = 1000

_locks = defaultdict(threading.Lock)


def case_lock(client_id: str) -> threading.Lock:
    """One case, one writer at a time: two quick clicks can't interleave their changes."""
    return _locks[client_id]


class NotAllowed(Exception):
    """The user's role, or the case's state, does not permit this action."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require(user: str, role: str) -> None:
    if user not in USERS:
        raise NotAllowed(f"unknown user {user!r}")
    if role not in USERS[user]["roles"]:
        raise NotAllowed(f"{user} does not hold the {role} role")


def _note(text: str, what: str = "note") -> str:
    text = (text or "").strip()
    if len(text) > MAX_NOTE:
        raise NotAllowed(f"the {what} is longer than {MAX_NOTE} characters")
    return text


class Case:
    def __init__(self, data: dict, cases_dir: Path = CASES_DIR):
        self.data, self.dir = data, Path(cases_dir)

    @property
    def client_id(self) -> str:
        return self.data["client_id"]

    @property
    def status(self) -> str:
        return self.data["status"]

    def _paths(self):
        return self.dir / f"{self.client_id}.json", self.dir / f"{self.client_id}.audit.jsonl"

    @property
    def assigned_rm(self) -> str:
        return self.data.get("assigned_rm") or DEFAULT_RM

    def save(self) -> None:
        path, _ = self._paths()
        atomic_write(path, json.dumps(self.data, indent=2, default=str))

    def _require_owner(self, user: str) -> None:
        """Object-level access: only the case's RM, or a manager, works the case."""
        _require(user, "rm")
        if user != self.assigned_rm and "manager" not in USERS[user]["roles"]:
            raise NotAllowed(f"this case is assigned to {self.assigned_rm}; only they or a "
                             "manager can change it")

    def _audit(self, user: str, action: str, before: str, details: dict | None = None) -> None:
        _, audit = self._paths()
        self.dir.mkdir(parents=True, exist_ok=True)
        entry = {"at": _now(), "user": user, "roles": USERS.get(user, {}).get("roles", []),
                 "action": action, "from": before, "to": self.status, "details": details or {}}
        with open(audit, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def audit_log(self) -> list[dict]:
        _, audit = self._paths()
        if not audit.exists():
            return []
        return [json.loads(line) for line in audit.read_text("utf-8").splitlines() if line]

    def _move(self, user: str, action: str, allowed_from: tuple, to: str,
              details: dict | None = None) -> None:
        if self.status not in allowed_from:
            raise NotAllowed(f"cannot {action} a case that is {self.status}")
        before = self.status
        self.data["status"] = to
        self.save()
        self._audit(user, action, before, details)

    # --- RM -------------------------------------------------------------------------
    def rm_edit(self, user: str, section: str, text: str) -> None:
        self._require_owner(user)
        text = (text or "").strip()
        if not text or len(text) > 4 * MAX_NOTE:
            raise NotAllowed(f"a memo section must have between 1 and {4 * MAX_NOTE} characters")
        if self.status != "awaiting_rm":
            raise NotAllowed(f"the memo can only be edited while awaiting RM review, not {self.status}")
        sections = {s["title"]: s for s in self.data["memo"]["sections"]}
        if section not in sections:
            raise NotAllowed(f"no memo section {section!r}")
        before = sections[section]["text"]
        sections[section]["text"] = text
        sections[section]["edited_by"] = user
        self.data.setdefault("edits", []).append({"at": _now(), "user": user, "section": section,
                                                  "before": before, "after": text})
        self.save()
        self._audit(user, "edit_memo", self.status, {"section": section, "before": before,
                                                     "after": text})

    def rm_submit(self, user: str, note: str = "") -> None:
        self._require_owner(user)
        note = _note(note)
        if not self.data.get("memo"):
            raise NotAllowed("there is no memo to submit; the agent stopped this case")
        if self.status != "awaiting_rm":
            raise NotAllowed(f"cannot submit a case that is {self.status}")
        self.data["submitted_by"] = user
        self._move(user, "submit", ("awaiting_rm",), "submitted", {"note": note})

    # --- approver -------------------------------------------------------------------
    def approver_decide(self, user: str, decision: str, note: str = "") -> None:
        _require(user, "approver")
        note = _note(note)
        if decision not in ("approved", "declined"):
            raise NotAllowed("decision must be approved or declined")
        if user == self.data.get("submitted_by"):
            raise NotAllowed("maker-checker: the person who submitted a case cannot decide it")
        if not note:
            raise NotAllowed("record a reason with the decision")
        if self.status != "submitted":
            raise NotAllowed(f"cannot decide a case that is {self.status}")
        limit = APPROVAL_LIMITS.get(user, 0)
        if self.data["requested_amount"] > limit:
            raise NotAllowed(f"K{self.data['requested_amount']:,} is above your delegated limit of "
                             f"K{limit:,}; escalate it to credit risk for a higher authority")
        if decision == "approved" and (self.data.get("score") or {}).get("band") == "High" \
                and not self._resolved("credit_risk"):
            raise NotAllowed("a High-risk case needs a resolved credit-risk escalation before approval")
        self.data["decision"] = {"by": user, "decision": decision, "note": note, "at": _now()}
        self._move(user, "decide", ("submitted",), decision, {"decision": decision, "note": note})

    # --- escalation -----------------------------------------------------------------
    def _resolved(self, to: str) -> bool:
        return any(e.get("to") == to and e.get("resolution") for e in self.data.get("human_escalations", []))

    def open_escalation(self) -> dict | None:
        return next((e for e in self.data.get("human_escalations", []) if not e.get("resolution")), None)

    def escalate(self, user: str, to: str, reason: str) -> dict:
        roles = set(USERS.get(user, {}).get("roles", []))
        if not roles & {"rm", "approver"}:
            raise NotAllowed(f"{user} cannot escalate cases")
        if to not in ESCALATE_TO:
            raise NotAllowed(f"escalate to one of: {', '.join(ESCALATE_TO)}")
        reason = _note(reason, "reason")
        if not reason:
            raise NotAllowed("give a reason for the escalation")
        if self.status not in ("awaiting_rm", "submitted", "approved"):
            raise NotAllowed(f"cannot escalate a case that is {self.status}")
        if self.open_escalation():
            raise NotAllowed("this case already has an open escalation")
        entry = {"to": to, "by": user, "reason": reason, "at": _now(), "from_status": self.status}
        self.data.setdefault("human_escalations", []).append(entry)
        self._move(user, "escalate", (self.status,), "escalated", {"to": to, "reason": reason})
        return entry

    def resolve(self, user: str, resolution: str, note: str) -> dict:
        _require(user, "approver")
        note = _note(note)
        entry = self.open_escalation()
        if self.status != "escalated" or not entry:
            raise NotAllowed("there is no open escalation on this case")
        if user == entry["by"]:
            raise NotAllowed("the person who escalated a case cannot resolve it")
        if resolution not in ("return", "decline"):
            raise NotAllowed("resolution must be return (to the RM) or decline")
        if not note:
            raise NotAllowed("record a note with the resolution")
        entry.update(resolution=resolution, resolved_by=user, note=note, resolved_at=_now())
        if resolution == "decline":
            self.data["decision"] = {"by": user, "decision": "declined", "note": note, "at": _now()}
            to = "declined"
        else:
            self.data.pop("submitted_by", None)
            to = "awaiting_rm"
        self._move(user, "resolve", ("escalated",), to, {"resolution": resolution, "note": note})
        return entry

    # --- disbursement ---------------------------------------------------------------
    def disburse(self, user: str) -> dict:
        if not set(USERS.get(user, {}).get("roles", [])) & {"rm", "approver"}:
            raise NotAllowed(f"{user} cannot trigger a disbursement")
        decision = self.data.get("decision") or {}
        if self.status != "approved" or decision.get("decision") != "approved":
            raise NotAllowed("money moves only after an approver's recorded approval")
        payout = momo_sandbox_payout(self.data)
        self.data["disbursement"] = payout
        self._move(user, "disburse", ("approved",), "disbursed", payout)
        return payout

    # --- auditor --------------------------------------------------------------------
    def view(self, user: str) -> dict:
        if user not in USERS:
            raise NotAllowed(f"unknown user {user!r}")
        return {"case": self.data, "audit": self.audit_log()}


def momo_sandbox_payout(data: dict) -> dict:
    """A mocked MoMo disbursement: the reference is derived from the case, nothing is sent."""
    wallet = data.get("payout_account")
    ref = hashlib.sha256(f"{data['client_id']}:{data['decision']['at']}".encode()).hexdigest()[:10]
    return {"sandbox": True, "provider": "MTN MoMo sandbox (mocked)", "to": wallet,
            "amount": data["requested_amount"], "currency": "ZMW",
            "transaction_id": f"SBX-{ref.upper()}", "status": "SUCCESSFUL", "at": _now()}


def open_case(run: dict, agent_case, cases_dir: Path = CASES_DIR,
              assigned_rm: str = DEFAULT_RM) -> Case:
    """Create the case file from a finished agent run (overwrites an earlier one)."""
    client = agent_case.client
    data = {
        "client_id": client["client_id"],
        "assigned_rm": assigned_rm,
        "business_name": client["business_name"],
        "requested_amount": client["application"]["requested_amount"],
        "payout_account": client["channels"].get("mtn") or client["channels"].get("airtel")
        or client["channels"]["absa"],
        "status": run["status"],
        "prepared_by": f"Insaka agent ({run['model']})",
        "escalations": run["escalations"],
        "checks": run["checks"],
        "score": agent_case.memo["score"] if agent_case.memo else None,
        "memo": {"sections": agent_case.memo["sections"], "written_by": agent_case.memo["written_by"]}
        if agent_case.memo else None,
        "agent_run": {k: run[k] for k in ("mode", "model", "steps_used", "refused_calls",
                                          "tokens", "replayed", "model_fallback", "steps")},
        "figures": {k: f.to_dict() for k, f in agent_case.assessment["figures"].items()}
        if agent_case.assessment else {},
        "verification": _verification(agent_case.report),
    }
    case = Case(data, cases_dir)
    save_ledger(agent_case, Path(cases_dir))
    _, audit = case._paths()
    if audit.exists():
        audit.unlink()   # a fresh run starts a fresh case
    case.save()
    case._audit("insaka.agent", "prepare", "preparing",
                {"steps": run["steps_used"], "escalations": len(run["escalations"])})
    return case


def _verification(report: dict | None) -> dict | None:
    if not report:
        return None
    return {"passed": report["passed"], "flagged_rows": report["flagged_rows"],
            "statements": report["statements"],
            "transfers": {k: len(v) for k, v in report["transfers"].items()}}


LEDGER_FIELDS = ("row_id", "channel", "date", "description", "reference", "direction",
                 "amount", "balance", "trust", "category", "label_source", "label_quote",
                 "needs_review")


def save_ledger(agent_case, cases_dir: Path) -> None:
    """The labelled rows behind the case, so the RM can open any figure's source."""
    rows = [{k: getattr(r, k) for k in LEDGER_FIELDS}
            for s in agent_case.ordered_statements() for r in s.rows]
    atomic_write(cases_dir / f"{agent_case.client_id}.ledger.json", json.dumps(rows))


def load_ledger(client_id: str, cases_dir: Path = CASES_DIR) -> list[dict]:
    path = Path(cases_dir) / f"{client_id}.ledger.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else []


def load_case(client_id: str, cases_dir: Path = CASES_DIR) -> Case:
    path = Path(cases_dir) / f"{client_id}.json"
    return Case(json.loads(path.read_text("utf-8")), cases_dir)
