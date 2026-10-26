import { useEffect, useState } from "react";
import { api, fmtFigure, kwacha, MONTHS } from "./api.js";

// What to know before the visit. Every line was built by code from the case and opens
// the figures or statement lines it rests on.
export default function Brief({ cid, user, c, open }) {
  const [b, setB] = useState(null);
  useEffect(() => { setB(null); api(`/cases/${cid}/brief`, user).then(setB); }, [cid, user]);
  if (!b) return <section className="card"><p className="muted">Loading…</p></section>;

  const openFigure = (name) => {
    const f = c.figures[name];
    if (f) open({ title: fmtFigure(f), label: f.label, rows: f.rows, detail: f.detail });
  };
  const chips = (names) => names.map((n) => c.figures[n] && (
    <button key={n} className="figure small" onClick={() => openFigure(n)}>{fmtFigure(c.figures[n])}</button>
  ));
  const t = b.trend;

  return (
    <div className="brief">
      {t && (
        <section className="card brief-card">
          <h3>Cash-flow trend</h3>
          <Sparkline series={t.series} />
          <p>{t.text}</p>
          <div className="brief-links">
            <button className="link" onClick={() => open({ title: kwacha(t.recent.income), label: `Business income, ${t.recent.months}`, rows: t.recent.rows })}>
              {t.recent.months}: {kwacha(t.recent.income)}
            </button>
            <button className="link" onClick={() => open({ title: kwacha(t.before.income), label: `Business income, ${t.before.months}`, rows: t.before.rows })}>
              {t.before.months}: {kwacha(t.before.income)}
            </button>
          </div>
          {b.context.map((x, i) => <p key={i} className="muted small-note">{x.text} {chips(x.figures)}</p>)}
        </section>
      )}
      <section className="card brief-card">
        <h3>Products the client doesn't hold</h3>
        <p className="muted small-note">Suggestions to discuss at the visit. Catalogue and holdings are mocked in the prototype.</p>
        {b.products.length ? (
          <ul className="brief-list">
            {b.products.map((p) => (
              <li key={p.product}>
                <b>{p.name}</b>: {p.what}
                <div className="why">Why: {p.why}{" "}
                  {p.rows.length > 0 && (
                    <button className="link" onClick={() => open({ title: p.name, label: p.why, rows: p.rows })}>
                      see {p.rows.length} lines
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : <p className="muted">Nothing to suggest from the statements.</p>}
      </section>
      <section className="card brief-card">
        <h3>Open issues</h3>
        <ul className="brief-list">
          {b.open_issues.map((x, i) => (
            <li key={i} className={`issue issue-${x.kind}${x.stop ? " stop" : ""}`}>
              {x.text}{" "}
              {x.rows?.length > 0 && (
                <button className="link" onClick={() => open({ title: `${x.rows.length} lines`, label: x.text, rows: x.rows })}>
                  see lines
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="card brief-card">
        <h3>Risk flags</h3>
        {b.risk_flags.length ? (
          <ul className="brief-list">
            {b.risk_flags.map((x, i) => <li key={i}><span className="flag-icon" aria-hidden>!</span> {x.text} {chips(x.figures)}</li>)}
          </ul>
        ) : <p className="muted">No risk findings in the statements.</p>}
      </section>
    </div>
  );
}

function Sparkline({ series }) {
  const W = 320, H = 64, P = 6;
  const max = Math.max(...series.map((s) => s.value), 1);
  const x = (i) => P + (i / Math.max(series.length - 1, 1)) * (W - 2 * P);
  const y = (v) => H - P - (v / max) * (H - 2 * P - 12);
  const d = series.map((s, i) => `${i ? "L" : "M"}${x(i)},${y(s.value)}`).join("");
  const last = series.length - 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="sparkline" role="img" aria-label="Business income by month">
      <path d={d} className="spark-line" />
      {series.map((s, i) => (
        <circle key={s.month} cx={x(i)} cy={y(s.value)} r={i >= last - 2 ? 3.5 : 2.5}
                className={i >= last - 2 ? "spark-dot recent" : "spark-dot"}>
          <title>{`${MONTHS[+s.month.slice(5) - 1]} ${s.month.slice(0, 4)}: ${kwacha(s.value)}`}</title>
        </circle>
      ))}
      <text x={x(0)} y={H - 1} className="axis">{MONTHS[+series[0].month.slice(5) - 1]}</text>
      <text x={x(last)} y={H - 1} className="axis" textAnchor="end">{MONTHS[+series[last].month.slice(5) - 1]}</text>
    </svg>
  );
}
