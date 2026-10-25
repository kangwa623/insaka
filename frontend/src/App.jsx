import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtFigure, kwacha, STATUS } from "./api.js";
import AgentPanel from "./AgentPanel.jsx";
import Actions from "./Actions.jsx";
import CashflowChart from "./CashflowChart.jsx";
import Evaluation from "./Evaluation.jsx";
import Memo from "./Memo.jsx";
import Pamodzi from "./Pamodzi.jsx";
import Pipeline from "./Pipeline.jsx";
import SourceDrawer from "./SourceDrawer.jsx";
import { AuditTrail, Transactions } from "./Tables.jsx";

export default function App() {
  const [users, setUsers] = useState([]);
  const [user, setUser] = useState("rm.chanda");
  const [cases, setCases] = useState([]);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState("MWILA-001");
  const [view, setView] = useState(null);       // {client, case, audit}
  const [ledger, setLedger] = useState([]);
  const params = new URLSearchParams(window.location.search);
  const [tab, setTab] = useState(params.get("tab") || "memo");
  const [screen, setScreen] = useState(["evaluation", "pipeline"].includes(params.get("view")) ? params.get("view") : "cases");
  const [drawer, setDrawer] = useState(null);   // {title, value, label, source, rows}
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [replayKey, setReplayKey] = useState(0);

  const notify = (text, kind = "info") => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 5000);
  };

  useEffect(() => { api("/users").then(setUsers); }, []);
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
  const me = users.find((u) => u.id === user);
  const shown = cases.filter((c) =>
    `${c.business_name} ${c.client_id} ${c.town}`.toLowerCase().includes(filter.toLowerCase()));
  const c = view?.case;
  const client = view?.client;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="wordmark">Insaka</span>
          <span className="tagline">Every figure traceable, every decision human.</span>
        </div>
        <nav className="screens">
          {[["cases", "Cases"], ["pipeline", "Pipeline"], ["evaluation", "Evaluation"]].map(([k, l]) => (
            <button key={k} className={screen === k ? "on" : ""} onClick={() => { setScreen(k); if (k !== "cases") loadCases(); }}>{l}</button>
          ))}
        </nav>
        <span className="pill synthetic">Synthetic data · prototype</span>
        <label className="signin">
          Signed in as
          <select value={user} onChange={(e) => setUser(e.target.value)}>
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.name} ({u.roles.join(" + ")})</option>
            ))}
          </select>
        </label>
      </header>

      {screen === "evaluation" ? <Evaluation user={user} /> :
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
          {client && (
            <>
              <ClientHeader client={client} c={c} />
              <Actions c={c} client={client} me={me} busy={busy} act={act} />
              {c && (
                <>
                  <nav className="tabs">
                    {[["memo", "Credit memo"], ["cashflow", "Cash flow"], ["pamodzi", "Pamodzi view"],
                      ["transactions", "Transactions"], ["audit", "Audit trail"]].map(([k, l]) => (
                      <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
                    ))}
                  </nav>
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
      {toast && <div className={`toast ${toast.kind}`}>{toast.text}</div>}
    </div>
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
