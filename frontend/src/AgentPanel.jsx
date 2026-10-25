import { useEffect, useState } from "react";
import { TOOL_LABELS } from "./api.js";

const STEP_MS = 450;

function summary(step) {
  const r = step.result || {};
  if (step.status === "refused") return `Refused by code: ${r.refused || r}`;
  if (step.status === "error") return r.error;
  if (step.status === "model_unavailable") return r;
  switch (step.tool) {
    case "read_statement": return `${r.rows} rows, ${r.from} to ${r.to}`;
    case "request_documents": return `Upload link sent (simulated), consent screen shown`;
    case "verify_statements":
      return r.passed ? `All statements reconcile; ${r.transfers_matched} transfers matched with Absa`
                      : `${r.flagged_rows} rows flagged by the tamper check or cross-match`;
    case "label_transactions": return `${r.rows} rows labelled by ${r.labelled_by}`;
    case "check_registration": case "check_tax_status": case "check_credit_bureau":
      return `${r.service}: ${String(r.status).replace("_", " ")} (mocked)`;
    case "score_risk": return `${r.risk_band} risk, ${(r.probability_of_default * 100).toFixed(1)}% PD`;
    case "draft_memo": return `${r.figures_used} figures, all linked; ${r.numbers_without_source} unsupported`;
    case "escalate": return r.case_stopped ? "Case stopped for a person" : "Flagged for the RM";
    case "submit_for_review": return "Handed to the RM";
    default: return "";
  }
}

// What the agent did, step by step, and why. A refused step shows that code, not the
// model, had the last word.
export default function AgentPanel({ run, escalations, replayKey, onReplay }) {
  const steps = run?.steps || [];
  const [shown, setShown] = useState(steps.length);

  useEffect(() => {
    if (!replayKey) { setShown(steps.length); return; }
    setShown(0);
    const t = setInterval(() => setShown((n) => {
      if (n >= steps.length) { clearInterval(t); return n; }
      return n + 1;
    }), STEP_MS);
    return () => clearInterval(t);
  }, [replayKey, steps.length]);

  return (
    <aside className="agent">
      <div className="agent-head">
        <h3>Agent activity</h3>
        {steps.length > 0 && <button className="link" onClick={onReplay}>Replay</button>}
      </div>
      {!run ? (
        <p className="muted">The agent hasn't run on this case.</p>
      ) : (
        <>
          <div className="agent-meta">
            {run.mode === "rules" ? "Deterministic agent" : run.model.replace("qwen/", "Qwen ")} ·{" "}
            {run.steps_used} steps · {run.refused_calls} refused · no tool can approve or pay out
          </div>
          <ol className="steps">
            {steps.slice(0, shown).map((s, i) => (
              <li key={i} className={`step st-${s.status}`}>
                <span className="dot" aria-hidden>{s.status === "ok" ? "✓" : s.status === "refused" ? "✕" : "!"}</span>
                <div>
                  <div className="step-tool">{TOOL_LABELS[s.tool] || s.tool || "No tool called"}
                    {s.args?.channel && <span className="arg"> {s.args.channel.toUpperCase()}</span>}
                    {s.args?.channels && <span className="arg"> {s.args.channels.join(", ").toUpperCase()}</span>}
                  </div>
                  {s.reason && <div className="step-why">{s.reason}</div>}
                  <div className="step-result">{summary(s)}</div>
                </div>
              </li>
            ))}
            {shown < steps.length && <li className="step working"><span className="dot">…</span><div>Working</div></li>}
          </ol>
          {shown >= steps.length && (
            <div className={`handover ${escalations.some((e) => e.stop) ? "stop" : ""}`}>
              {escalations.some((e) => e.stop) ? "Stopped: a person takes over." : "Waiting for the RM."}
            </div>
          )}
        </>
      )}
    </aside>
  );
}
