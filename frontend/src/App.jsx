import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtFigure, kwacha, session, STATUS } from "./api.js";
import ErrorBoundary from "./ErrorBoundary.jsx";
import Login from "./Login.jsx";
import Security from "./Security.jsx";
import AgentPanel from "./AgentPanel.jsx";
import Actions, { Escalate } from "./Actions.jsx";
import CashflowChart from "./CashflowChart.jsx";
import Brief from "./Brief.jsx";
import Documents from "./Documents.jsx";
import Evaluation from "./Evaluation.jsx";
import Memo from "./Memo.jsx";
import Pamodzi from "./Pamodzi.jsx";
import Pipeline from "./Pipeline.jsx";
import SourceDrawer from "./SourceDrawer.jsx";
import { AuditTrail, Transactions } from "./Tables.jsx";

// Nothing loads until a staff member has signed in with a password and an authenticator
// code; the session ends when the tab closes, on sign-out, or after 30 minutes.
export default function App() {
  const [signedIn, setSignedIn] = useState(() => session.get()?.user || null);
  useEffect(() => {
    const out = () => setSignedIn(null);
    window.addEventListener("insaka:signed-out", out);
    return () => window.removeEventListener("insaka:signed-out", out);
  }, []);
  const signOut = async () => {
    await api("/auth/logout", null, { method: "POST" }).catch(() => {});
    session.clear();
    setSignedIn(null);
  };
  if (!signedIn) {
    return (
      <ErrorBoundary>
        <Login onSignedIn={(s) => {
          session.set({ token: s.access_token, user: s.user, expiresAt: Date.now() + s.expires_in * 1000 });
          setSignedIn(s.user);
        }} />
      </ErrorBoundary>
    );
  }
  return <ErrorBoundary><Workspace signedIn={signedIn} onSignOut={signOut} /></ErrorBoundary>;
}

const SECURITY_ROLES = ["auditor", "approver", "manager"];

function Workspace({ signedIn, onSignOut }) {
  const [users, setUsers] = useState([]);
  const user = signedIn.id;
  const [cases, setCases] = useState([]);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState("MWILA-001");
  const [view, setView] = useState(null);       // {client, case, audit}
  const [ledger, setLedger] = useState([]);
  const params = new URLSearchParams(window.location.search);
  const [tab, setTab] = useState(params.get("tab") || "memo");
  const [screen, setScreen] = useState(["evaluation", "pipeline", "security"].includes(params.get("view")) ? params.get("view") : "cases");
  const canSeeSecurity = signedIn.roles.some((r) => SECURITY_ROLES.includes(r));
  const [health, setHealth] = useState(null);
  const [drawer, setDrawer] = useState(null);   // {title, value, label, source, rows}
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [replayKey, setReplayKey] = useState(0);

  const notify = (text, kind = "info") => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 5000);
  };

  // Free hosting sleeps when idle: if the first call is slow, say so until it answers.
  const [waking, setWaking] = useState(false);
  useEffect(() => {
    const slow = setTimeout(() => setWaking(true), 3000);
    api("/users").then(setUsers).catch((e) => notify(e.message, "error"))
      .finally(() => { clearTimeout(slow); setWaking(false); });
  }, []);

  // Reliability: show when the AI is on its fallbacks; warn before the session ends.
  useEffect(() => {
    const check = () => api("/health").then(setHealth).catch(() => setHealth(null));
    check();
    const t = setInterval(check, 60000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const t = setInterval(() => {
      const left = (session.get()?.expiresAt || 0) - Date.now();
      if (left > 0 && left < 120000) notify("Your session ends in under 2 minutes. Save your work; you'll need to sign in again.");
    }, 60000);
    return () => clearInterval(t);
  }, []);
  const loadCases = useCallback(() => api("/cases", user).then(setCases).catch((e) => notify(e.message, "error")), [user]);
  useEffect(() => { loadCases(); }, [loadCases]);

  const loadCase = useCallback(async () => {
    if (!selected) return;
    const v = await api(`/cases/${selected}`, user);
    setView(v);
    setLedger(v.case ? await api(`/cases/${selected}/ledger`, user) : []);
  }, [selected, user]);
  useEffect(() => { setDrawer(null); loadCase().catch((e) => notify(e.message, "error")); }, [loadCase]);

  const act = async (path, body, success) => {
    setBusy(true);
    try {
      const v = await api(`/cases/${selected}/${path}`, user, { method: "POST", body });
      setView(v);
      if (path === "run") {
        setLedger(await api(`/cases/${selected}/ledger`, user));
        setReplayKey((k) => k + 1);
      }
      if (success) notify(success, "ok");
      loadCases();
      return v;
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  // ?figure=<name> opens that figure's sources once the case has loaded (handy for demos).
  useEffect(() => {
    const name = params.get("figure");
    const fig = view?.case?.figures?.[name];
    if (fig && ledger.length) setDrawer({ title: fmtFigure(fig), label: fig.label, rows: fig.rows, detail: fig.detail });
  }, [view, ledger]);  // eslint-disable-line react-hooks/exhaustive-deps

  const rowsById = useMemo(() => Object.fromEntries(ledger.map((r) => [r.row_id, r])), [ledger]);
  const me = signedIn;
  const shown = cases.filter((c) =>
    `${c.business_name} ${c.client_id} ${c.town}`.toLowerCase().includes(filter.toLowerCase()));
  const c = view?.case;
  const client = view?.client;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="wordmark">Insaka</span>
          <span className="tagline">Every business has a story.</span>
        </div>
        <nav className="screens">
          {[["cases", "Cases"], ["pipeline", "Pipeline"], ["evaluation", "Evaluation"],
            ...(canSeeSecurity ? [["security", "Security"]] : [])].map(([k, l]) => (
            <button key={k} className={screen === k ? "on" : ""} onClick={() => { setScreen(k); if (k !== "cases") loadCases(); }}>{l}</button>
          ))}
        </nav>
        <span className="pill synthetic">Synthetic data<span className="pill-more"> · prototype</span></span>
        <div className="signin">
          <span className="who"><b>{signedIn.name}</b> <small>{signedIn.roles.join(" · ")}</small></span>
          <button className="signout" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      {health && health.ai !== "available" && (
        <div className="degraded" role="status">
          AI assistance is unavailable right now ({health.model?.configured ? `model ${health.model.state}` : "not configured"}).
          Insaka is using its deterministic fallbacks: the rules agent, keyword labels and the template memo. Every check still runs.
        </div>
      )}

      {screen === "evaluation" ? <Evaluation user={user} /> :
       screen === "security" && canSeeSecurity ? <Security user={user} /> :
       screen === "pipeline" ? <Pipeline cases={cases} openCase={(cid) => { setSelected(cid); setTab("memo"); setScreen("cases"); }} /> : (
      <div className="layout">
        <aside className="cases">
          <input className="search" placeholder="Search cases" value={filter}
                 onChange={(e) => setFilter(e.target.value)} />
          <ul>
            {shown.map((k) => (
              <li key={k.client_id} className={k.client_id === selected ? "active" : ""}
                  onClick={() => { setSelected(k.client_id); setTab("memo"); }}>
                <div className="case-name">{k.business_name}</div>
                <div className="case-meta">
                  {k.town} · {kwacha(k.requested_amount)}
                </div>
                <span className={`status s-${k.status}`}>{STATUS[k.status]}</span>
              </li>
            ))}
          </ul>
        </aside>

        <main className="main">
          <CasePicker cases={cases} selected={selected}
                      onPick={(cid) => { setSelected(cid); setTab("memo"); }} />
          {client && (
            <>
              <ClientHeader client={client} c={c} />
              <Actions c={c} client={client} me={me} busy={busy} act={act} />
              <Escalate c={c} me={me} busy={busy} act={act} />
              <Documents key={`${selected}-${c?.status}`} cid={selected} user={user} me={me} notify={notify} />
              {c && (
                <>
                  <nav className="tabs">
                    {[["brief", "Pre-visit brief"], ["memo", "Credit memo"], ["cashflow", "Cash flow"], ["pamodzi", "Pamodzi view"],
                      ["transactions", "Transactions"], ["audit", "Audit trail"]].map(([k, l]) => (
                      <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
                    ))}
                  </nav>
                  {tab === "brief" && <Brief cid={selected} user={user} c={c} open={setDrawer} />}
                  {tab === "memo" && <Memo c={c} me={me} busy={busy} act={act} rowsById={rowsById} open={setDrawer} />}
                  {tab === "cashflow" && <CashflowChart c={c} ledger={ledger} open={setDrawer} />}
                  {tab === "pamodzi" && <Pamodzi cid={selected} user={user} open={setDrawer} />}
                  {tab === "transactions" && <Transactions ledger={ledger} />}
                  {tab === "audit" && <AuditTrail audit={view.audit} users={users} />}
                </>
              )}
            </>
          )}
        </main>

        <AgentPanel run={c?.agent_run} escalations={c?.escalations || []} replayKey={replayKey}
                    onReplay={() => setReplayKey((k) => k + 1)} />
      </div>
      )}

      {drawer && <SourceDrawer drawer={drawer} rowsById={rowsById} close={() => setDrawer(null)} />}
      {waking && <div className="toast">Waking the server (free hosting sleeps when idle); this can take up to a minute…</div>}
      {toast && <div className={`toast ${toast.kind}`}>{toast.text}</div>}
    </div>
  );
}

// On tablets and phones the case list gives way to this picker (shown by CSS below 900px).
const STAGE_ORDER = ["awaiting_rm", "submitted", "approved", "escalated", "disbursed", "declined", "not_started"];

function CasePicker({ cases, selected, onPick }) {
  return (
    <label className="case-picker">
      <span>Case</span>
      <select value={selected} onChange={(e) => onPick(e.target.value)}>
        {STAGE_ORDER.map((status) => {
          const list = cases.filter((k) => k.status === status);
          return list.length > 0 && (
            <optgroup key={status} label={`${STATUS[status]} (${list.length})`}>
              {list.map((k) => (
                <option key={k.client_id} value={k.client_id}>
                  {k.business_name} · {k.town} · {kwacha(k.requested_amount)}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
    </label>
  );
}

function ClientHeader({ client, c }) {
  const app = client.application;
  const score = c?.score;
  const checks = c?.checks || {};
  const checkText = {
    found: "Registered, active", not_registered: "Not registered (informal)", not_found: "Not found",
    compliant: "TPIN confirmed", no_record: "No record of TPIN",
    clean: "Clean record", no_hit: "No history (thin file)", adverse: "Adverse record",
  };
  const good = new Set(["found", "compliant", "clean"]);
  return (
    <section className="client card">
      <div className="client-top">
        <div>
          <h1>{client.business_name}</h1>
          <div className="muted">
            {client.business_type} · {client.town}, {client.province} Province · {client.years_trading} years trading
          </div>
          <div className="request">
            Requests <b>{kwacha(app.requested_amount)}</b> over {app.tenor_months} months: {app.purpose}
          </div>
        </div>
        <div className="client-right">
          <span className={`status big s-${c?.status || "not_started"}`}>{STATUS[c?.status || "not_started"]}</span>
          {score && (
            <div className={`band band-${score.band.toLowerCase()}`}>
              <span>{score.band} risk</span>
              <b>{(score.pd * 100).toFixed(1)}%</b>
              <small>estimated probability of default</small>
            </div>
          )}
        </div>
      </div>
      {Object.keys(checks).length > 0 && (
        <div className="checks">
          {Object.values(checks).map((k) => (
            <span key={k.service} className={`check ${good.has(k.status) ? "ok" : k.status === "no_hit" || k.status === "not_registered" ? "warn" : "bad"}`}>
              <span aria-hidden>{good.has(k.status) ? "✓" : "!"}</span>
              <b>{k.service}</b> {checkText[k.status]}
              {k.mocked && <em>mocked</em>}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
