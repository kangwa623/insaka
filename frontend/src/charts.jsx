import { useState } from "react";

// Small SVG charts for the Evaluation screen: thin marks, one axis each, values on hover,
// and every chart paired with a table (see TableView) so nothing depends on colour alone.

const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
export const num = (v, d = 3) => (v === null || v === undefined || Number.isNaN(v) ? "n/a" : v.toFixed(d));

function steps([lo, hi]) {
  const out = [];
  for (let v = lo; v <= hi + 1e-9; v += 0.1) out.push(Math.round(v * 10) / 10);
  return out;
}

function useTip() {
  const [tip, setTip] = useState(null);
  const show = (e, content) => {
    const box = e.currentTarget.ownerSVGElement.getBoundingClientRect();
    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content });
  };
  return [tip, show, () => setTip(null)];
}

function Tip({ tip }) {
  if (!tip) return null;
  return <div className="tooltip eval-tip" style={{ left: tip.x, top: tip.y + 14 }}>{tip.content}</div>;
}

function Axis({ x, y, ticks, fmt, height }) {
  return ticks.map((t) => (
    <g key={t}>
      <line x1={x(t)} x2={x(t)} y1={y} y2={y + height} className="grid" />
      <text x={x(t)} y={y + height + 14} className="axis" textAnchor="middle">{fmt(t)}</text>
    </g>
  ));
}

/** Point estimates with 95% intervals, one row per item, on one shared axis. */
export function IntervalChart({ items, domain = [0.5, 1], fmt = (v) => num(v, 2), label }) {
  const [tip, show, hide] = useTip();
  const W = 520, rowH = 30, L = 150, R = 20, T = 6;
  const H = T + items.length * rowH + 22;
  // Clamped to the axis; the tooltip and the table give the exact interval.
  const x = (v) => L + ((Math.min(Math.max(v, domain[0]), domain[1]) - domain[0]) / (domain[1] - domain[0])) * (W - L - R);
  const ticks = steps(domain);
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <Axis x={x} y={T} ticks={ticks} fmt={(v) => v.toFixed(1)} height={items.length * rowH} />
        {items.map((it, i) => {
          const cy = T + i * rowH + rowH / 2;
          return (
            <g key={it.label} onMouseMove={(e) => show(e, <>
              <b>{it.label}</b><div>{fmt(it.value)}{it.lo !== undefined && ` [${fmt(it.lo)}, ${fmt(it.hi)}]`}</div></>)}
               onMouseLeave={hide}>
              <rect x={0} y={cy - rowH / 2} width={W} height={rowH} className="hit" />
              <text x={L - 10} y={cy} className="row-label" textAnchor="end" dominantBaseline="middle">{it.label}</text>
              {it.lo !== undefined && (
                <>
                  <line x1={x(it.lo)} x2={x(it.hi)} y1={cy} y2={cy} className={`whisker ${it.muted ? "muted-mark" : ""}`} />
                  <line x1={x(it.lo)} x2={x(it.lo)} y1={cy - 5} y2={cy + 5} className={`whisker ${it.muted ? "muted-mark" : ""}`} />
                  <line x1={x(it.hi)} x2={x(it.hi)} y1={cy - 5} y2={cy + 5} className={`whisker ${it.muted ? "muted-mark" : ""}`} />
                </>
              )}
              <circle cx={x(it.value)} cy={cy} r={5} className={`dot-mark ${it.muted ? "muted-mark" : "s1"}`} />
            </g>
          );
        })}
      </svg>
      <Tip tip={tip} />
    </div>
  );
}

/** Two values per category (e.g. Qwen vs rules), joined by a thin line. */
export function DumbbellChart({ rows, series, domain = [0.5, 1], label }) {
  const [tip, show, hide] = useTip();
  const W = 760, rowH = 24, L = 160, R = 20, T = 6;
  const H = T + rows.length * rowH + 22;
  const x = (v) => L + ((Math.max(v, domain[0]) - domain[0]) / (domain[1] - domain[0])) * (W - L - R);
  const ticks = steps(domain);
  return (
    <div className="chart-wrap dumbbell">
      <div className="legend">
        {series.map((s, i) => <span key={s.key}><i className={`sw sw-s${i + 1}`} />{s.label}</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <Axis x={x} y={T} ticks={ticks} fmt={(v) => v.toFixed(1)} height={rows.length * rowH} />
        {rows.map((r, i) => {
          const cy = T + i * rowH + rowH / 2;
          const vals = series.map((s) => r[s.key]);
          return (
            <g key={r.label} onMouseMove={(e) => show(e, <>
              <b>{r.label}</b>
              {series.map((s, k) => <div key={s.key}><i className={`sw sw-s${k + 1}`} />{s.label} <span>{num(r[s.key], 3)}</span></div>)}
              {r.note && <small>{r.note}</small>}</>)} onMouseLeave={hide}>
              <rect x={0} y={cy - rowH / 2} width={W} height={rowH} className="hit" />
              <text x={L - 10} y={cy} className="row-label" textAnchor="end" dominantBaseline="middle">{r.label}</text>
              <line x1={x(Math.min(...vals))} x2={x(Math.max(...vals))} y1={cy} y2={cy} className="connector" />
              {vals.map((v, k) => {
                const tie = vals.filter((w) => Math.abs(w - v) < 0.002).length > 1;
                return <circle key={k} cx={x(v) + (tie ? (k ? 6 : -6) : 0)} cy={cy} r={5}
                               className={`dot-mark s${k + 1} ring`} />;
              })}
            </g>
          );
        })}
      </svg>
      <Tip tip={tip} />
    </div>
  );
}

/** Predicted vs observed rate by group of clients, with the line of perfect calibration. */
export function CalibrationChart({ bins, label }) {
  const [tip, show, hide] = useTip();
  const W = 360, H = 300, M = { l: 52, r: 16, t: 12, b: 40 };
  const top = Math.ceil(Math.max(...bins.flatMap((b) => [b.mean_predicted, b.observed_default_rate])) * 10) / 10 || 1;
  const x = (v) => M.l + (v / top) * (W - M.l - M.r);
  const y = (v) => H - M.b - (v / top) * (H - M.t - M.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * top);
  const path = bins.map((b, i) => `${i ? "L" : "M"}${x(b.mean_predicted)},${y(b.observed_default_rate)}`).join("");
  return (
    <div className="chart-wrap calibration">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={M.l - 6} y={y(t)} className="axis" textAnchor="end" dominantBaseline="middle">{pct(t, 0)}</text>
            <text x={x(t)} y={H - M.b + 14} className="axis" textAnchor="middle">{pct(t, 0)}</text>
          </g>
        ))}
        <line x1={x(0)} y1={y(0)} x2={x(top)} y2={y(top)} className="diagonal" />
        <text x={x(top) - 4} y={y(top) + 14} className="axis" textAnchor="end">perfect calibration</text>
        <path d={path} className="cal-line" />
        {bins.map((b, i) => (
          <g key={i} onMouseMove={(e) => show(e, <>
            <b>Group {i + 1} of {bins.length}</b>
            <div>Predicted <span>{pct(b.mean_predicted)}</span></div>
            <div>Observed <span>{pct(b.observed_default_rate)}</span></div>
            <small>{b.clients} clients</small></>)} onMouseLeave={hide}>
            <circle cx={x(b.mean_predicted)} cy={y(b.observed_default_rate)} r={12} className="hit" />
            <circle cx={x(b.mean_predicted)} cy={y(b.observed_default_rate)} r={5} className="dot-mark s1 ring" />
          </g>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 6} className="axis-title" textAnchor="middle">Predicted default rate</text>
        <text x={12} y={(M.t + H - M.b) / 2} className="axis-title" textAnchor="middle"
              transform={`rotate(-90 12 ${(M.t + H - M.b) / 2})`}>Observed default rate</text>
      </svg>
      <Tip tip={tip} />
    </div>
  );
}

export function TableView({ head, rows }) {
  return (
    <details className="table-view">
      <summary>Show as table</summary>
      <div className="table-scroll"><table className="rows">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, k) => <td key={k}>{c}</td>)}</tr>)}</tbody>
      </table></div>
    </details>
  );
}
