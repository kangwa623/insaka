import { useState } from "react";
import { CATEGORY_LABELS, CHANNELS, kwacha } from "./api.js";
import { Trust } from "./SourceDrawer.jsx";

export function Transactions({ ledger }) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [limit, setLimit] = useState(150);
  const rows = ledger.filter((r) => (!cat || r.category === cat)
    && `${r.description} ${r.row_id}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <section className="card">
      <div className="filters">
        <input placeholder="Search descriptions" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">All categories</option>
          {Object.entries(CATEGORY_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="muted">{rows.length} of {ledger.length} rows</span>
      </div>
      <table className="rows">
        <thead>
          <tr><th>Date</th><th>Source</th><th>Description</th><th>Category</th><th>Labelled by</th><th className="num">Amount</th><th>Trust</th></tr>
        </thead>
        <tbody>
          {rows.slice(0, limit).map((r) => (
            <tr key={r.row_id} title={r.row_id}>
              <td>{r.date}</td>
              <td>{CHANNELS[r.channel]}</td>
              <td>{r.description}{r.needs_review && <span className="review"> needs review</span>}</td>
              <td>{CATEGORY_LABELS[r.category] || r.category}</td>
              <td className="muted" title={r.label_quote ? `Quoted: “${r.label_quote}”` : ""}>
                {r.label_source.startsWith("llm:") ? "Qwen" : "Rules"}
              </td>
              <td className={`num ${r.direction}`}>{r.direction === "debit" ? "−" : "+"}{kwacha(r.amount)}</td>
              <td><Trust level={r.trust} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > limit && <button className="link" onClick={() => setLimit((l) => l + 300)}>Show more</button>}
    </section>
  );
}

const ACTIONS = { prepare: "Prepared the case", edit_memo: "Edited the memo", submit: "Submitted to the approver",
                  decide: "Recorded a decision", disburse: "Disbursed through the MoMo sandbox" };

export function AuditTrail({ audit, users }) {
  const name = (id) => users.find((u) => u.id === id)?.name || id;
  return (
    <section className="card">
      <p className="muted">Every action on this case, in order. Entries are appended, never changed.</p>
      <ol className="audit">
        {audit.map((e, i) => (
          <li key={i}>
            <div><b>{name(e.user)}</b> {ACTIONS[e.action] || e.action}
              {e.details?.decision && <> : <b>{e.details.decision}</b></>}
              {e.details?.section && <> : {e.details.section}</>}
            </div>
            <div className="muted">{new Date(e.at).toLocaleString()} · {e.from} → {e.to}
              {e.details?.note && <> · “{e.details.note}”</>}
              {e.details?.transaction_id && <> · {e.details.transaction_id}</>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
