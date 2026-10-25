"""The rules code enforces around the agent, whichever model is choosing the steps.

The model decides the order of work; code decides what is allowed. A tool call that
breaks a rule is refused with the reason, logged, and handed back to the model, so a
confused or manipulated model cannot skip a check or finish early. The brief's rules:
- history under six months: request a mobile-money statement;
- transfers that don't match Absa's records (or a failed tamper check): escalate for an
  RM spot-check of the references;
- PACRA can't find a business the applicant says is registered: stop and escalate.
RulesChat is a deterministic agent that follows the same rules in a fixed order: the
baseline, the test double, and the fallback when the model is unavailable.
"""

from .tools import ESCALATION_KINDS, MIN_MONTHS, TOOLS, AgentCase

STEP_LIMIT = 20


def pacra_stop_required(case: AgentCase) -> bool:
    return case.checks.get("pacra", {}).get("status") == "not_found"


def required_escalations(case: AgentCase) -> dict[str, str]:
    """Escalations the evidence so far demands, by kind, with why."""
    need = {}
    if case.report and case.report["flagged_rows"]:
        need["spot_check"] = (f"{len(case.report['flagged_rows'])} rows failed the tamper check "
                              "or the transfer cross-match")
    if case.labelling and case.labelling["injection_suspected"]:
        need["suspicious_text"] = "statement text reads like instructions"
    if case.checks.get("zra", {}).get("status") == "no_record":
        need["registration"] = "ZRA has no record of the declared TPIN"
    if pacra_stop_required(case):
        need["registration"] = "PACRA cannot find the declared business"
    if (case.months_covered() and case.months_covered() < MIN_MONTHS
            and all(w in case.requested for w in case.wallets_listed)):
        need["thin_history"] = f"statements cover fewer than {MIN_MONTHS} months"
    return need


def missing_before_submit(case: AgentCase) -> list[str]:
    missing = []
    unrequested = [w for w in case.wallets_listed if w not in case.requested]
    if case.months_covered() < MIN_MONTHS and unrequested:
        missing.append(f"statements cover {case.months_covered()} months, under "
                       f"{MIN_MONTHS}: request the mobile-money statement(s) {unrequested}")
    raised = {e["kind"] for e in case.escalations}
    for kind, why in required_escalations(case).items():
        if kind not in raised:
            missing.append(f"escalate (kind {kind}): {why}")
    if case.memo is None:
        missing.append("draft the memo first")
    return missing


def refusal(case: AgentCase, name: str, args: dict) -> str | None:
    """Why this call is not allowed now, or None if it may run."""
    if name not in TOOLS:
        return (f"there is no tool {name!r}. Insaka cannot approve, decline or disburse a loan; "
                f"available tools: {', '.join(TOOLS)}")
    if not args.get("reason"):
        return "give a reason with every tool call; the RM sees it"
    if pacra_stop_required(case) and not (name == "escalate" and args.get("stop")):
        return ("PACRA cannot find this business: the only allowed step is escalate with "
                "kind registration and stop=true")
    if name == "read_statement":
        ch = args.get("channel")
        if ch not in case.available:
            return (f"the {ch} statement is not available; request it with request_documents"
                    if ch in case.wallets_listed else
                    f"the applicant did not list a {ch} account")
        if ch in case.statements:
            return f"the {ch} statement has already been read"
    elif name == "request_documents":
        chans = args.get("channels") or []
        bad = [c for c in chans if c not in case.wallets_listed]
        if not chans or bad:
            return f"the applicant listed these wallets only: {case.wallets_listed}"
        if all(c in case.requested for c in chans):
            return f"{chans} already requested"
    elif name == "verify_statements":
        unread = sorted(case.available - set(case.statements))
        if not case.statements:
            return "read a statement first"
        if unread:
            return f"read every available statement first: {unread}"
    elif name == "label_transactions" and case.report is None:
        return "verify the statements first"
    elif name == "score_risk":
        if case.labelling is None:
            return "label the transactions first"
        missing = [c for c in ("pacra", "zra", "bureau") if c not in case.checks]
        if missing:
            return f"run the {', '.join(missing)} check(s) first"
    elif name == "draft_memo" and case.assessment is None:
        return "score the risk first"
    elif name == "escalate":
        if args.get("kind") not in ESCALATION_KINDS:
            return f"kind must be one of {ESCALATION_KINDS}"
    elif name == "submit_for_review":
        missing = missing_before_submit(case)
        if missing:
            return "not ready: " + "; ".join(missing)
    return None


class RulesChat:
    """A deterministic agent: the policy's steps in a fixed order."""

    model = "rules"

    def __init__(self, case: AgentCase):
        self.case = case
        self.n = 0

    def next_call(self) -> tuple[str, dict]:
        c = self.case
        if "absa" not in c.statements:
            return "read_statement", {"channel": "absa", "reason": "The Absa history is held "
                                      "internally, so it comes first."}
        unrequested = [w for w in c.wallets_listed if w not in c.requested]
        if unrequested:
            why = (f"The Absa history covers {c.months_covered()} months, under "
                   f"{MIN_MONTHS}; a mobile-money statement is required."
                   if c.months_covered() < MIN_MONTHS else
                   "The applicant listed these wallets; they complete the picture of income.")
            return "request_documents", {"channels": unrequested, "reason": why}
        unread = [ch for ch in ("mtn", "airtel") if ch in c.available and ch not in c.statements]
        if unread:
            return "read_statement", {"channel": unread[0],
                                      "reason": f"The customer uploaded the {unread[0]} statement."}
        if c.report is None:
            return "verify_statements", {"reason": "Check for edits and cross-match transfers "
                                         "before using any figure."}
        if "pacra" not in c.checks:
            return "check_registration", {"reason": "Confirm the business exists before analysis."}
        if pacra_stop_required(c):
            return "escalate", {"kind": "registration", "stop": True,
                                "reason": "PACRA cannot find the business the applicant says is "
                                          "registered; a person must look into it."}
        if c.labelling is None:
            return "label_transactions", {"reason": "Categorise every row so income and costs "
                                          "can be computed."}
        for key, tool in (("zra", "check_tax_status"), ("bureau", "check_credit_bureau")):
            if key not in c.checks:
                return tool, {"reason": "A required check before scoring."}
        raised = {e["kind"] for e in c.escalations}
        for kind, why in required_escalations(c).items():
            if kind not in raised:
                return "escalate", {"kind": kind, "stop": False,
                                    "reason": f"For the RM: {why}."}
        if c.assessment is None:
            return "score_risk", {"reason": "All checks done; compute features and the score."}
        if c.memo is None:
            return "draft_memo", {"reason": "Write the case up with every figure linked."}
        return "submit_for_review", {"reason": "The case is ready for the RM."}

    def turn(self, messages, tools) -> dict:
        self.n += 1
        name, args = self.next_call()
        return {"text": "", "calls": [{"id": f"rules-{self.n}", "name": name, "arguments": args}],
                "tokens": 0}
