import { useMemo, useState } from "react";
import { CHANNELS, fmtFigure as fmt, kwacha, MONTHS } from "./api.js";
import { TableView } from "./charts.jsx";

// Business income by month, one stacked bar per month: bank and wallets combined into
// one picture of how the business trades. Months come from the memo's own figure, so
// the bars add up to exactly what the memo says; click a month for its statement lines.
const SERIES = ["absa", "mtn", "airtel"];   // fixed order: colour follows the channel
const W = 760, H = 300, M = { top: 16, right: 12, bottom: 34, left: 64 };

function niceMax(v) {
  const p = 10 ** Math.floor(Math.log10(v || 1));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v);
}

function topRounded(x, y, w, h, r) {
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export default function CashflowChart({ c, ledger, open }) {
  const [hover, setHover] = useState(null);
  const byMonth = c.figures.monthly_income?.detail?.by_month || {};
  const rowsById = useMemo(() => Object.fromEntries(ledger.map((r) => [r.row_id, r])), [ledger]);

  const data = Object.entries(byMonth).map(([month, m]) => {
    const parts = Object.fromEntries(SERIES.map((s) => [s, 0]));
    for (const id of m.rows) {
      const r = rowsById[id];
      if (r) parts[r.channel] += r.amount;
    }
    return { month, total: m.value, parts, rows: m.rows };
  });
  const present = SERIES.filter((s) => data.some((d) => d.parts[s] > 0));
  const max = niceMax(Math.max(...data.map((d) => d.total), 1));
  const iw = W - M.left - M.right, ih = H - M.top - M.bottom;
  const band = iw / Math.max(data.length, 1);
  const bw = Math.min(44, band * 0.62);
  const y = (v) => M.top + ih - (v / max) * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const f = c.figures;

  const tile = (name, sub) => f[name] && (
    <button className="tile" onClick={() => open({ title: fmt(f[name]), label: f[name].label, rows: f[name].rows, detail: f[name].detail })}>
      <span>{f[name].label}</span><b>{fmt(f[name])}</b>{sub && <small>{sub}</small>}
    </button>
  );

  return (
    <section className="card cashflow viz-root">
      <div className="tiles">
        {tile("mean_monthly_income")}
        {tile("peak_month_income")}
        {tile("deseasoned_income_cv")}
        {tile("mobile_money_share")}
      </div>
      <h3>Business income by month</h3>
      <div className="legend">
        {present.map((s) => (
          <span key={s}><i className={`sw sw-${s}`} />{CHANNELS[s]}</span>
        ))}
      </div>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Business income by month and channel">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="grid" />
              <text x={M.left - 8} y={y(t)} className="axis" textAnchor="end" dominantBaseline="middle">{kwacha(t)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = M.left + i * band + (band - bw) / 2;
            let base = 0;
            const segs = present.filter((s) => d.parts[s] > 0);
            const [yy, mm] = d.month.split("-");
            return (
              <g key={d.month}>
                {segs.map((s, k) => {
                  const y0 = y(base), y1 = y(base + d.parts[s]);
                  base += d.parts[s];
                  const h = Math.max(0, y0 - y1 - (k > 0 ? 2 : 0));   // 2px gap between segments
                  const top = k === segs.length - 1;
                  return top ? <path key={s} d={topRounded(x, y1, bw, h, 4)} className={`bar bar-${s}`} />
                             : <rect key={s} x={x} y={y1} width={bw} height={h} className={`bar bar-${s}`} />;
                })}
                <text x={x + bw / 2} y={H - M.bottom + 16} className="axis" textAnchor="middle">
                  {MONTHS[+mm - 1]}{mm === "01" || i === 0 ? ` ${yy.slice(2)}` : ""}
                </text>
                <rect x={M.left + i * band} y={M.top} width={band} height={ih} className="hit"
                      onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                      onClick={() => open({ title: kwacha(d.total), label: `Business income in ${MONTHS[+mm - 1]} ${yy}`, rows: d.rows })} />
              </g>
            );
          })}
          <line x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)} className="baseline" />
        </svg>
        {hover !== null && (
          <div className="tooltip" style={{ left: `${((M.left + (hover + 0.5) * band) / W) * 100}%` }}>
            <b>{data[hover].month}</b>
            {present.map((s) => <div key={s}><i className={`sw sw-${s}`} />{CHANNELS[s]} <span>{kwacha(data[hover].parts[s])}</span></div>)}
            <div className="tt-total">Total <span>{kwacha(data[hover].total)}</span></div>
            <small>Click to see the statement lines</small>
          </div>
        )}
      </div>
      <TableView head={["Month", ...present.map((s) => CHANNELS[s]), "Total"]}
                 rows={data.map((d) => [d.month, ...present.map((s) => kwacha(d.parts[s])), kwacha(d.total)])} />
    </section>
  );
}
