import { kwacha } from "./api.js";

// Every case by stage, from application to money paid out. The memo stage is where Insaka
// changes the work: each prepared card shows how long the agent took to make the case
// decision-ready.
const COLUMNS = [
  ["not_started", "Application", "Waiting for Insaka to prepare"],
  ["escalated", "Escalated", "The agent stopped for a person"],
  ["awaiting_rm", "With the RM", "Memo ready to review"],
  ["submitted", "With the approver", "Waiting for a decision"],
  ["approved", "Approved", "Ready to pay out"],
  ["disbursed", "Disbursed", "Paid through MoMo sandbox"],
  ["declined", "Declined", ""],
];
const APPLICATIONS_SHOWN = 6;

function since(at) {
  if (!at) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(at).getTime()) / 60000));
  if (mins < 60) return `${mins} min in stage`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h in stage`;
  return `${Math.round(mins / 1440)} days in stage`;
}

function duration(s) {
  return s < 60 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 60)} min`;
}

export default function Pipeline({ cases, openCase }) {
  const prepared = cases.filter((c) => c.prepared_in_seconds !== null);
  const times = prepared.map((c) => c.prepared_in_seconds).sort((a, b) => a - b);
  const median = times.length ? times[Math.floor(times.length / 2)] : null;
  const live = cases.filter((c) => !["not_started", "declined", "disbursed"].includes(c.status));
  const value = live.reduce((a, c) => a + c.requested_amount, 0);

  return (
    <div className="pipeline">
      <header className="eval-head">
        <h1>Pipeline</h1>
        <p className="muted">Every case from application to payout. Click a card to open the case.</p>
      </header>
      <div className="tiles pipeline-tiles">
        <div className="tile static"><span>Cases in progress</span><b>{live.length}</b><small>{kwacha(value)} requested</small></div>
        <div className="tile static"><span>Memo ready in (median)</span><b>{median !== null ? duration(median) : "–"}</b>
          <small>agent time, across {prepared.length} prepared cases; drafted by hand this takes days</small></div>
        <div className="tile static"><span>Escalated to a person</span><b>{cases.filter((c) => c.status === "escalated").length}</b></div>
        <div className="tile static"><span>Paid out</span><b>{cases.filter((c) => c.status === "disbursed").length}</b>
          <small>{kwacha(cases.filter((c) => c.status === "disbursed").reduce((a, c) => a + c.requested_amount, 0))}</small></div>
      </div>
      <div className="board">
        {COLUMNS.map(([status, title, hint]) => {
          const list = cases.filter((c) => c.status === status);
          const shown = status === "not_started" ? list.slice(0, APPLICATIONS_SHOWN) : list;
          return (
            <section key={status} className={`column col-${status}`}>
              <h3>{title} <span className="count">{list.length}</span></h3>
              {hint && <div className="hint">{hint}</div>}
              {shown.map((c) => (
                <button key={c.client_id} className="deal" onClick={() => openCase(c.client_id)}>
                  <div className="deal-name">{c.business_name}</div>
                  <div className="deal-meta">{c.town} · {kwacha(c.requested_amount)}</div>
                  <div className="deal-tags">
                    {c.band && <span className={`band-chip band-${c.band.toLowerCase()}`}>{c.band} risk</span>}
                    {c.escalations > 0 && <span className="esc-chip">! {c.escalations} flagged</span>}
                  </div>
                  {c.prepared_in_seconds !== null && <div className="deal-time">Memo ready in {duration(c.prepared_in_seconds)}</div>}
                  {c.stage_since && <div className="deal-time muted">{since(c.stage_since)}</div>}
                </button>
              ))}
              {list.length > shown.length && <div className="more">+ {list.length - shown.length} more applications</div>}
            </section>
          );
        })}
      </div>
    </div>
  );
}
