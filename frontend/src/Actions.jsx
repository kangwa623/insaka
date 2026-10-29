import { useState } from "react";
import { kwacha } from "./api.js";

const TEAMS = { credit_risk: "Credit risk", compliance: "Compliance", fraud: "Fraud" };

// Anyone working a case can escalate it with a reason; someone else with approval
// authority resolves it. The server enforces both.
export function Escalate({ c, me, busy, act }) {
  const [openForm, setOpenForm] = useState(false);
  const [to, setTo] = useState("credit_risk");
  const [reason, setReason] = useState("");
  const roles = me?.roles || [];
  if (!c || !["awaiting_rm", "submitted", "approved"].includes(c.status)) return null;
  if (!roles.some((r) => r === "rm" || r === "approver")) return null;
  return (
    <section className="card escalate">
      {!openForm ? (
        <button className="link" onClick={() => setOpenForm(true)}>Escalate this case…</button>
      ) : (
        <div className="escalate-form">
          <b>Escalate for a second look</b>
          <div className="buttons">
            <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="Escalate to">
              {Object.entries(TEAMS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <input placeholder="Reason (required)" value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
            <button className="secondary" disabled={busy || !reason.trim()}
                    onClick={() => act("escalate", { to, reason }, `Escalated to ${TEAMS[to]}`).then(() => { setOpenForm(false); setReason(""); })}>
              Escalate
            </button>
            <button className="link" onClick={() => setOpenForm(false)}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}

function Resolve({ c, open, me, busy, act }) {
  const [note, setNote] = useState("");
  const isApprover = (me?.roles || []).includes("approver");
  return (
    <section className="actions card escalated-card">
      <div>
        <b>Escalated to {TEAMS[open.to]} by {open.by}</b>: “{open.reason}”
        <div className="muted">Someone other than {open.by}, with approval authority, resolves it: back to the RM, or decline.</div>
      </div>
      {isApprover && (
        <div className="buttons">
          <input placeholder="Resolution note (required)" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          <button className="primary" disabled={busy || !note.trim()}
                  onClick={() => act("resolve", { resolution: "return", note }, "Returned to the RM").then(() => setNote(""))}>
            Return to RM
          </button>
          <button className="secondary" disabled={busy || !note.trim()}
                  onClick={() => act("resolve", { resolution: "decline", note }, "Declined").then(() => setNote(""))}>
            Decline
          </button>
        </div>
      )}
    </section>
  );
}

// The next human step for this case. Buttons follow the signed-in role, but the server
// decides: a refused action comes back as an error and is shown, not hidden.
export default function Actions({ c, client, me, busy, act }) {
  const [note, setNote] = useState("");
  const roles = me?.roles || [];
  const isRm = roles.includes("rm");
  const isApprover = roles.includes("approver");
  const status = c?.status || "not_started";
  const open = (c?.human_escalations || []).find((e) => !e.resolution);

  if (status === "escalated" && open) {
    return <Resolve c={c} open={open} me={me} busy={busy} act={act} />;
  }

  if (status === "not_started" || status === "escalated") {
    return (
      <section className="actions card">
        <div>
          <b>{status === "escalated" ? "The agent stopped and handed this case to a person." : "No case prepared yet."}</b>
          <div className="muted">
            {isRm ? "Insaka reads the statements, runs the checks and drafts the memo, then hands it back to you."
                  : "An RM starts the case."}
          </div>
        </div>
        {isRm && (
          <div className="buttons">
            <button className="primary" disabled={busy} onClick={() => act("run", { mode: "llm" }, "Case prepared")}>
              {busy ? "Preparing…" : status === "escalated" ? "Re-run Insaka" : "Prepare case with Insaka"}
            </button>
          </div>
        )}
      </section>
    );
  }

  if (status === "awaiting_rm") {
    return (
      <section className="actions card">
        <div>
          <b>Review the memo.</b>
          <div className="muted">Click any figure to see the statement lines behind it. Edit a section if it needs it, then submit to an approver.</div>
        </div>
        {isRm && (
          <div className="buttons">
            <input placeholder="Note for the approver (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="primary" disabled={busy}
                    onClick={() => act("submit", { note }, "Submitted to the approver").then(() => setNote(""))}>
              Submit to approver
            </button>
          </div>
        )}
      </section>
    );
  }

  if (status === "submitted") {
    return (
      <section className="actions card">
        <div>
          <b>Decision needed.</b>
          <div className="muted">
            Submitted by {c.submitted_by}. The person who submitted a case cannot decide it.
          </div>
        </div>
        {isApprover && (
          <div className="buttons">
            <input placeholder="Reason for the decision (required)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="primary" disabled={busy}
                    onClick={() => act("decide", { decision: "approved", note }, "Approved").then(() => setNote(""))}>
              Approve
            </button>
            <button className="secondary" disabled={busy}
                    onClick={() => act("decide", { decision: "declined", note }, "Declined").then(() => setNote(""))}>
              Decline
            </button>
          </div>
        )}
      </section>
    );
  }

  if (status === "approved") {
    return (
      <section className="actions card">
        <div>
          <b>Approved by {c.decision.by}</b>: “{c.decision.note}”
          <div className="muted">Pay out {kwacha(c.requested_amount)} to {c.payout_account} through the MoMo sandbox.</div>
        </div>
        {(isRm || isApprover) && (
          <div className="buttons">
            <button className="primary" disabled={busy} onClick={() => act("disburse", {}, "Disbursement confirmed")}>
              Disburse via MoMo sandbox
            </button>
          </div>
        )}
      </section>
    );
  }

  if (status === "disbursed") {
    const d = c.disbursement;
    return (
      <section className="actions card receipt">
        <div>
          <b>✓ Disbursed: {kwacha(d.amount)} to {d.to}</b>
          <div className="muted">{d.provider} · transaction {d.transaction_id} · {d.status} · {new Date(d.at).toLocaleString()}</div>
        </div>
      </section>
    );
  }

  return (
    <section className="actions card">
      <div><b>Declined by {c.decision.by}</b>: “{c.decision.note}”</div>
    </section>
  );
}
