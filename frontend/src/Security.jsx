import { useEffect, useState } from "react";
import { api, kwacha } from "./api.js";

// How Insaka answers the OWASP Top 10 (2025) and the OWASP Top 10 for LLM applications
// (2025): each risk, the control, where it lives, the test that proves it, and its live
// state from the server. Full detail is in SECURITY.md.

function Badge({ state, children }) {
  const icon = { met: "✓", check: "!", na: "–" }[state];
  return <span className={`eval-status es-${state === "met" ? "met" : state === "check" ? "check" : "pending"}`}>
    <span aria-hidden>{icon}</span> {children}</span>;
}

function owasp(s) {
  const prod = s.secrets.from_environment;
  return [
    ["A01", "Broken Access Control", "Deny-by-default role checks on every route; only the case's RM or a manager works a case; maker-checker; delegated approval limits; auditors read-only.",
      "api.py requires(), case.py", "test_security: object-level access, maker-checker, limits", "met"],
    ["A02", "Security Misconfiguration", `Security headers and CSP on API and site; CORS ${s.cors.restricted ? "limited to the Insaka site" : "open (local development)"}; secrets only from the environment${prod ? "" : " (development defaults in use here)"}.`,
      "security.py, firebase.json, render.yaml", "test_security: headers", s.cors.restricted && prod ? "met" : "check"],
    ["A03", "Software Supply Chain Failures", "Pinned Python and npm versions, Dependabot, CI with pip-audit and npm audit; the language model is pinned by name.",
      "requirements.txt, package-lock.json, .github/", "CI workflow", "met"],
    ["A04", "Cryptographic Failures", "HTTPS only (HSTS); scrypt password hashes; signed, expiring tokens; TOTP secrets derived from a server key, never stored.",
      "auth.py", "test_auth: forged and expired tokens", "met"],
    ["A05", "Injection", "No SQL or shell; client ids validated before any file path; statement text treated as data, never instructions; React escapes all text.",
      "security.valid_client_id, labelling/injection.py", "test_security: path traversal", "met"],
    ["A06", "Insecure Design", "Threat-modelled flow: people decide, the agent cannot approve or pay; escalation must be resolved by someone else; High-risk cases need a credit-risk review.",
      "case.py, agent/policy.py", "test_security, test_agent", "met"],
    ["A07", "Authentication Failures", `Password + authenticator code (MFA); replay protection; lockout after 5 tries; 10 sign-ins a minute per address; 30-minute sessions; sign-out revokes.${s.mfa.demo_helper ? " Demo code helper is ON for judges." : ""}`,
      "auth.py", "test_auth", s.mfa.demo_helper ? "check" : "met"],
    ["A08", "Software or Data Integrity Failures", `Risk model loads only if its SHA-256 matches (${s.risk_model_verified ? "verified" : "NOT verified"}); tamper check on statements; hash-chained security log; atomic case writes.`,
      "scoring/model.py, parsing/verify.py, security.EventLog", "test_security: tampered model, chain", s.risk_model_verified && s.event_log.intact ? "met" : "check"],
    ["A09", "Security Logging and Alerting Failures", `Every sign-in, refusal, lockout, escalation and decision is logged with a request id; the chain is ${s.event_log.intact ? "intact" : "BROKEN"} (${s.event_log.entries} events).`,
      "security.EventLog, api.py", "test_security: chain", s.event_log.intact ? "met" : "check"],
    ["A10", "Mishandling of Exceptional Conditions", "No stack traces to users; circuit breaker and fallbacks keep cases moving when the model fails; retries with backoff in the screens.",
      "api.py error handlers, labelling/llm.py", "test_security: circuit breaker", "met"],
  ];
}

function owaspAI(s) {
  return [
    ["LLM01", "Prompt Injection", "Statement text wrapped as untrusted data; instruction-like rows flagged for the RM; code refuses any tool call that breaks a rule.", "labelling/injection.py, agent/policy.py", "test_agent: adversarial model", "met"],
    ["LLM02", "Sensitive Information Disclosure", "Names, phone numbers and accounts are masked before any model call; the model never sees raw rows.", "labelling/masking.py", "test_security: prompts carry no personal data", "met"],
    ["LLM03", "Supply Chain", "Open model pinned by name; the scoring model is hash-checked before loading.", "labelling/llm.py, scoring/model.py", "test_security", "met"],
    ["LLM04", "Data and Model Poisoning", "The risk model is trained only on the synthetic generator, offline; labels are validated against the row they quote.", "scoring/, labelling/llm.py", "test_labelling", "met"],
    ["LLM05", "Improper Output Handling", "Model output must be valid JSON naming real rows and categories; memo text may not contain its own numbers or decisions; nothing is rendered as HTML.", "labelling/llm.py, memo.py", "test_memo, test_labelling", "met"],
    ["LLM06", "Excessive Agency", "The agent has no tool to approve, decline or pay; 20-step limit; people decide.", "agent/tools.py, agent/policy.py", "test_security: tool allow-list", "met"],
    ["LLM07", "System Prompt Leakage", "Prompts hold no secrets, keys or customer data; access control is in code, not in the prompt.", "labelling/llm.py, agent/loop.py", "review", "met"],
    ["LLM08", "Vector and Embedding Weaknesses", "Not applicable: Insaka uses no retrieval or embeddings.", "-", "-", "na"],
    ["LLM09", "Misinformation", "Code computes and inserts every figure, each linked to its source rows; 0 unsupported numbers across 1,661 figures.", "memo.py, features.py", "evaluation/memo.py", "met"],
    ["LLM10", "Unbounded Consumption", `Per-call output caps, 20-step limit, ${s.live_runs_per_hour} live runs per user per hour, daily token budget (${s.budget.used_today.toLocaleString()} of ${s.budget.daily_limit.toLocaleString()} used).`, "security.TokenBudget, api.py", "test_security", "met"],
  ];
}

export default function Security({ user }) {
  const [s, setS] = useState(null);
  const [ev, setEv] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api("/security/status").then(setS).catch((e) => setError(e.message));
    api("/security/events").then(setEv).catch(() => setEv(false));
  }, [user]);
  if (error) return <div className="eval"><p className="muted">{error}</p></div>;
  if (!s) return <div className="eval"><p className="muted">Loading…</p></div>;

  const table = (rows) => (
    <div className="table-scroll"><table className="rows sec-table">
      <thead><tr><th>Risk</th><th>Control in Insaka</th><th>Where</th><th>Proof</th><th>Status</th></tr></thead>
      <tbody>{rows.map(([id, name, control, where, proof, state]) => (
        <tr key={id}><td><b>{id}</b> {name}</td><td>{control}</td><td><code>{where}</code></td><td>{proof}</td>
          <td><Badge state={state}>{state === "met" ? "In place" : state === "check" ? "Note" : "N/A"}</Badge></td></tr>
      ))}</tbody>
    </table></div>
  );

  return (
    <div className="eval">
      <header className="eval-head">
        <h1>Security</h1>
        <p className="muted">How Insaka answers the OWASP Top 10 and the OWASP Top 10 for LLM applications, with each control's live state.
          Detail and the threat model are in SECURITY.md.</p>
      </header>

      <section className="card">
        <h2>Controls at a glance</h2>
        <div className="tiles">
          <div className="tile static"><span>Sign-in</span><b>Password + MFA</b><small>{s.mfa.method}{s.mfa.demo_helper ? " · demo helper on" : ""}</small></div>
          <div className="tile static"><span>Sessions</span><b>{s.sessions.access_token_minutes} min</b><small>lockout after {s.sessions.lockout_after} tries for {s.sessions.lockout_minutes} min</small></div>
          <div className="tile static"><span>AI model</span><b>{s.model.state === "closed" ? "Available" : "Fallback"}</b><small>circuit trips: {s.model.trips}</small></div>
          <div className="tile static"><span>Security log</span><b>{s.event_log.intact ? "Intact" : "Tampered"}</b><small>{s.event_log.entries} events, hash-chained</small></div>
        </div>
        <h3>Who can do what</h3>
        <div className="table-scroll"><table className="rows">
          <thead><tr><th>Role</th><th>Can</th><th>Cannot</th></tr></thead>
          <tbody>
            <tr><td><b>RM</b></td><td>Prepare, edit and submit their own cases; upload statements; escalate</td><td>Work another RM's case; approve; see security events</td></tr>
            <tr><td><b>Approver</b></td><td>Approve or decline within their limit ({Object.entries(s.approval_limits).map(([u, l]) => `${u} ${kwacha(l)}`).join(", ")}); resolve escalations; disburse after approval</td><td>Decide a case they submitted; resolve their own escalation; approve a High-risk case without a credit-risk review</td></tr>
            <tr><td><b>Manager</b></td><td>Everything an RM and approver can, on any case; read security events</td><td>Bypass maker-checker</td></tr>
            <tr><td><b>Auditor</b></td><td>Read every case, audit trail and security event</td><td>Change anything</td></tr>
            <tr><td><b>Insaka agent</b></td><td>Read, verify, label, score, draft, escalate</td><td>Approve, decline or pay; act without a reason; exceed 20 steps</td></tr>
          </tbody>
        </table></div>
      </section>

      <section className="card"><h2>OWASP Top 10 (2025)</h2>{table(owasp(s))}</section>
      <section className="card"><h2>OWASP Top 10 for LLM applications (2025)</h2>{table(owaspAI(s))}</section>

      <section className="card">
        <h2>Security events</h2>
        {ev === false ? <p className="muted">Security events are visible to auditors and managers.</p> : !ev ? <p className="muted">Loading…</p> : (
          <>
            <p className="muted">Chain check: <b>{ev.chain.intact ? "intact" : `broken at entry ${ev.chain.broken_at}`}</b> · {ev.chain.entries} events. Newest first.</p>
            <div className="table-scroll"><table className="rows">
              <thead><tr><th>When</th><th>Event</th><th>User</th><th>Details</th></tr></thead>
              <tbody>{ev.events.slice(0, 60).map((e) => (
                <tr key={e.hash} className={e.severity !== "info" ? "flag" : ""}>
                  <td>{new Date(e.at).toLocaleString()}</td><td>{e.event.replaceAll("_", " ")}</td><td>{e.user || "-"}</td>
                  <td className="muted">{Object.entries(e.details).filter(([k]) => !["request_id"].includes(k)).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" · ")}</td>
                </tr>
              ))}</tbody>
            </table></div>
          </>
        )}
      </section>
    </div>
  );
}
