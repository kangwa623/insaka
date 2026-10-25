"""The case after the agent: people review, decide and pay out, and every action is logged.

    preparing -> awaiting_rm -> submitted -> approved | declined -> disbursed
                 escalated (the agent stopped; a person takes over)

Roles are checked here, on the server side, not in the screens:
- an RM edits the memo and submits the case;
- an approver decides, and never on a case they submitted themselves (maker-checker);
- money moves only after a recorded approval, through the MoMo sandbox (mocked);
- an auditor can read everything and change nothing.
Each action is appended to {client}.audit.jsonl; nothing in the audit log is rewritten.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CASES_DIR = Path("data/cases")

# Synthetic staff for the prototype. One manager holds both roles, to show maker-checker.
USERS = {
    "rm.chanda": {"name": "Chanda M.", "roles": ["rm"]},
    "rm.mutale": {"name": "Mutale K.", "roles": ["rm"]},
    "approver.banda": {"name": "Banda S.", "roles": ["approver"]},
    "manager.zulu": {"name": "Zulu T.", "roles": ["rm", "approver"]},
    "auditor.phiri": {"name": "Phiri N.", "roles": ["auditor"]},
}


class NotAllowed(Exception):
    """The user's role, or the case's state, does not permit this action."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require(user: str, role: str) -> None:
    if user not in USERS:
        raise NotAllowed(f"unknown user {user!r}")
    if role not in USERS[user]["roles"]:
        raise NotAllowed(f"{user} does not hold the {role} role")


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

    def save(self) -> None:
        path, _ = self._paths()
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, indent=2, default=str), "utf-8")

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
        _require(user, "rm")
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
        _require(user, "rm")
        if not self.data.get("memo"):
            raise NotAllowed("there is no memo to submit; the agent stopped this case")
        self.data["submitted_by"] = user
        self._move(user, "submit", ("awaiting_rm",), "submitted", {"note": note})

    # --- approver -------------------------------------------------------------------
    def approver_decide(self, user: str, decision: str, note: str = "") -> None:
        _require(user, "approver")
        if decision not in ("approved", "declined"):
            raise NotAllowed("decision must be approved or declined")
        if user == self.data.get("submitted_by"):
            raise NotAllowed("maker-checker: the person who submitted a case cannot decide it")
        if not note.strip():
            raise NotAllowed("record a reason with the decision")
        self.data["decision"] = {"by": user, "decision": decision, "note": note, "at": _now()}
        self._move(user, "decide", ("submitted",), decision, {"decision": decision, "note": note})

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


def open_case(run: dict, agent_case, cases_dir: Path = CASES_DIR) -> Case:
    """Create the case file from a finished agent run (overwrites an earlier one)."""
    client = agent_case.client
    data = {
        "client_id": client["client_id"],
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
                                          "tokens", "replayed")},
    }
    case = Case(data, cases_dir)
    _, audit = case._paths()
    if audit.exists():
        audit.unlink()   # a fresh run starts a fresh case
    case.save()
    case._audit("insaka.agent", "prepare", "preparing",
                {"steps": run["steps_used"], "escalations": len(run["escalations"])})
    return case


def load_case(client_id: str, cases_dir: Path = CASES_DIR) -> Case:
    path = Path(cases_dir) / f"{client_id}.json"
    return Case(json.loads(path.read_text("utf-8")), cases_dir)
