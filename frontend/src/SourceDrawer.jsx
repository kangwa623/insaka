import { useState } from "react";
import { CATEGORY_LABELS, CHANNELS, kwacha } from "./api.js";

const TRUST_ICON = { Verified: "✓", "Cross-checked": "◐", Unverified: "!" };

export function Trust({ level }) {
  if (!level) return null;
  return (
    <span className={`trust t-${level.replace(" ", "").toLowerCase()}`}>
      <span aria-hidden>{TRUST_ICON[level]}</span> {level}
    </span>
  );
}

// Where a figure comes from: its statement lines, with trust levels, or the application
// or risk model when it is not a statement figure.
export default function SourceDrawer({ drawer, rowsById, close }) {
  const [limit, setLimit] = useState(60);
  const rows = (drawer.rows || []).map((id) => rowsById[id]).filter(Boolean);
  const trust = rows.reduce((acc, r) => ({ ...acc, [r.trust]: (acc[r.trust] || 0) + 1 }), {});
  const credits = rows.filter((r) => r.direction === "credit").reduce((a, r) => a + r.amount, 0);
  const debits = rows.filter((r) => r.direction === "debit").reduce((a, r) => a + r.amount, 0);

  return (
    <div className="drawer-backdrop" onClick={close}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Figure source">
        <button className="close" onClick={close} aria-label="Close">×</button>
        <div className="drawer-value">{drawer.title}</div>
        <div className="drawer-label">{drawer.label}</div>

        {rows.length > 0 ? (
          <>
            <div className="drawer-summary">
              Computed by code from <b>{rows.length}</b> statement {rows.length === 1 ? "line" : "lines"}
              {credits > 0 && <> · money in {kwacha(credits)}</>}
              {debits > 0 && <> · money out {kwacha(debits)}</>}
            </div>
            <div className="trust-row">
              {Object.entries(trust).map(([t, n]) => <span key={t}><Trust level={t} /> {n}</span>)}
            </div>
            <table className="rows">
              <thead>
                <tr><th>Date</th><th>Source</th><th>Description</th><th>Category</th><th className="num">Amount</th><th>Trust</th></tr>
              </thead>
              <tbody>
                {rows.slice(0, limit).map((r) => (
                  <tr key={r.row_id} title={r.row_id}>
                    <td>{r.date}</td>
                    <td>{CHANNELS[r.channel]}</td>
                    <td>{r.description}{r.needs_review && <span className="review"> needs review</span>}</td>
                    <td>{CATEGORY_LABELS[r.category] || r.category}</td>
                    <td className={`num ${r.direction}`}>{r.direction === "debit" ? "−" : "+"}{kwacha(r.amount)}</td>
                    <td><Trust level={r.trust} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > limit && (
              <button className="link" onClick={() => setLimit((l) => l + 200)}>
                Show more ({rows.length - limit} remaining)
              </button>
            )}
          </>
        ) : drawer.source === "risk model" ? (
          <div className="drawer-summary">
            From the logistic-regression risk model, which uses the statement figures and the application.
            <ReasonList title="Raises the estimate" items={drawer.score?.raises_risk} />
            <ReasonList title="Lowers the estimate" items={drawer.score?.lowers_risk} />
          </div>
        ) : (
          <div className="drawer-summary">
            {drawer.source === "application" ? "From the loan application the RM entered." :
              drawer.detail?.amount ? `Computed from the application: ${kwacha(drawer.detail.amount)} over ${drawer.detail.tenor_months} months at the quoted flat rate.` :
              "Computed from the statements."}
          </div>
        )}
      </aside>
    </div>
  );
}

function ReasonList({ title, items }) {
  if (!items?.length) return null;
  return (
    <div className="reasons">
      <b>{title}</b>
      <ul>{items.map((r) => <li key={r.input}>{r.text}</li>)}</ul>
    </div>
  );
}
