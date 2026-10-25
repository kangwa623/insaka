import { useState } from "react";
import { kwacha } from "./api.js";

// The next human step for this case. Buttons follow the signed-in role, but the server
// decides: a refused action comes back as an error and is shown, not hidden.
export default function Actions({ c, client, me, busy, act }) {
  const [note, setNote] = useState("");
  const roles = me?.roles || [];
  const isRm = roles.includes("rm");
  const isApprover = roles.includes("approver");
  const status = c?.status || "not_started";

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
