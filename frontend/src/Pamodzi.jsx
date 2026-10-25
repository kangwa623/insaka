import { useEffect, useState } from "react";
import { api, CHANNELS, kwacha, MONTHS } from "./api.js";

// Pamodzi: bank and wallets together, month by month. Money in above the axis, money out
// below, each stacked by channel; the net is a line on the same kwacha axis. Money moved
// between the owner's own accounts is left out (it would count twice) and shown apart.
const W = 760, H = 320, M = { top: 14, right: 12, bottom: 30, left: 70 };
const label = (m) => { const [y, mm] = m.split("-"); return `${MONTHS[+mm - 1]} ${y}`; };

function niceMax(v) {
  const p = 10 ** Math.floor(Math.log10(v || 1));
  return [1, 2, 2.5, 5, 10].map((k) => k * p).find((k) => k >= v);
}

export default function Pamodzi({ cid, user, open }) {
  const [p, setP] = useState(null);
  const [hover, setHover] = useState(null);
  useEffect(() => { setP(null); api(`/cases/${cid}/pamodzi`, user).then(setP); }, [cid, user]);
  if (!p) return <section className="card"><p className="muted">Loading…</p></section>;

  const t = p.totals, ch = p.channels;
  const max = niceMax(Math.max(...p.months.flatMap((m) => [m.in, m.out]), 1));
  const ih = H - M.top - M.bottom, iw = W - M.left - M.right;
  const y = (v) => M.top + ih / 2 - (v / max) * (ih / 2);
  const band = iw / p.months.length, bw = Math.min(40, band * 0.6);
  const ticks = [-1, -0.5, 0, 0.5, 1].map((k) => k * max);
  const cx = (i) => M.left + i * band + band / 2;
  const netPath = p.months.map((m, i) => `${i ? "L" : "M"}${cx(i)},${y(m.net)}`).join("");

  const tile = (name, value, rows, sub) => (
    <button className="tile" onClick={() => open({ title: kwacha(value), label: name, rows })}>
      <span>{name}</span><b>{kwacha(value)}</b>{sub && <small>{sub}</small>}
    </button>
  );

  return (
    <section className="card pamodzi">
      <div className="tiles">
        {tile("Money in", t.in, t.rows_in, ch.map((c) => `${CHANNELS[c]} ${Math.round(t.share_in_by_channel[c] * 100)}%`).join(" · "))}
        {tile("Money out", t.out, t.rows_out)}
        {tile("Average net per month", t.average_monthly_net, [...t.rows_in, ...t.rows_out])}
        {tile("Moved between own accounts", t.moved_between_own_accounts, t.rows_own, "left out of in and out")}
      </div>
      <h3>All accounts, month by month</h3>
      <div className="legend">
        {ch.map((c) => <span key={c}><i className={`sw sw-${c}`} />{CHANNELS[c]}</span>)}
        <span><i className="sw sw-net" />Net (in minus out)</span>
      </div>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Money in and out by month and account">
          {ticks.map((v) => (
            <g key={v}>
              <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className={v === 0 ? "baseline" : "grid"} />
              <text x={M.left - 8} y={y(v)} className="axis" textAnchor="end" dominantBaseline="middle">
                {v < 0 ? "−" : ""}{kwacha(Math.abs(v))}
              </text>
            </g>
          ))}
          <text x={M.left + 4} y={M.top + 10} className="axis">money in</text>
          <text x={M.left + 4} y={H - M.bottom - 4} className="axis">money out</text>
          {p.months.map((m, i) => {
            const x = cx(i) - bw / 2;
            let up = 0, down = 0;
            const [yy, mm] = m.month.split("-");
            return (
              <g key={m.month}>
                {ch.map((c) => {
                  const v = m.channels[c].in;
                  if (!v) return null;
                  const y1 = y(up + v), y0 = y(up);
                  up += v;
                  return <rect key={`i${c}`} x={x} y={y1} width={bw} height={Math.max(0, y0 - y1 - 1)} className={`bar bar-${c}`} />;
                })}
                {ch.map((c) => {
                  const v = m.channels[c].out;
                  if (!v) return null;
                  const y0 = y(-down), y1 = y(-(down + v));
                  down += v;
                  return <rect key={`o${c}`} x={x} y={y0 + 1} width={bw} height={Math.max(0, y1 - y0 - 1)} className={`bar bar-${c} out`} />;
                })}
                <text x={cx(i)} y={H - 10} className="axis" textAnchor="middle">
                  {MONTHS[+mm - 1]}{mm === "01" || i === 0 ? ` ${yy.slice(2)}` : ""}
                </text>
                <rect x={M.left + i * band} y={M.top} width={band} height={ih} className="hit"
                      onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                      onClick={() => open({ title: label(m.month), label: `Money in and out, ${label(m.month)}`,
                                            rows: [...m.rows_in, ...m.rows_out, ...m.rows_own] })} />
              </g>
            );
          })}
          <path d={netPath} className="net-line" />
          {p.months.map((m, i) => <circle key={m.month} cx={cx(i)} cy={y(m.net)} r={4} className="net-dot" />)}
        </svg>
        {hover !== null && (
          <div className="tooltip" style={{ left: `${(cx(hover) / W) * 100}%` }}>
            <b>{label(p.months[hover].month)}</b>
            {ch.map((c) => (
              <div key={c}><i className={`sw sw-${c}`} />{CHANNELS[c]}
                <span>+{kwacha(p.months[hover].channels[c].in)} / −{kwacha(p.months[hover].channels[c].out)}</span></div>
            ))}
            <div className="tt-total">Net <span>{kwacha(p.months[hover].net)}</span></div>
            <small>Click to see the statement lines</small>
          </div>
        )}
      </div>
      <p className="muted note">
        Money out includes cash withdrawals and household spending, so in and out come close over a year.
        The memo's surplus counts only committed business costs (suppliers, rent, wages, loans).
        {p.balance_check.mismatches.length === 0
          ? ` Balances reconcile in all ${p.balance_check.months_checked} account-months.`
          : ` ${p.balance_check.mismatches.length} account-months do not reconcile with their balances (an edited statement).`}
      </p>

      <table className="rows pamodzi-table">
        <thead>
          <tr><th rowSpan={2}>Month</th>
            {ch.map((c) => <th key={c} colSpan={3} className="group">{CHANNELS[c]}</th>)}
            <th colSpan={3} className="group">All accounts</th></tr>
          <tr>{ch.flatMap((c) => [<th key={`${c}i`} className="num">In</th>, <th key={`${c}o`} className="num">Out</th>,
            <th key={`${c}b`} className="num">Balance</th>])}
            <th className="num">In</th><th className="num">Out</th><th className="num">Net</th></tr>
        </thead>
        <tbody>
          {p.months.map((m) => (
            <tr key={m.month}>
              <td>{label(m.month)}</td>
              {ch.flatMap((c) => [<td key={`${c}i`} className="num">{kwacha(m.channels[c].in)}</td>,
                <td key={`${c}o`} className="num">{kwacha(m.channels[c].out)}</td>,
                <td key={`${c}b`} className="num muted">{kwacha(m.channels[c].end_balance)}</td>])}
              <td className="num"><b>{kwacha(m.in)}</b></td><td className="num"><b>{kwacha(m.out)}</b></td>
              <td className={`num ${m.net < 0 ? "neg" : ""}`}><b>{kwacha(m.net)}</b></td>
            </tr>
          ))}
          <tr className="total">
            <td>Total</td>
            {ch.flatMap((c) => [<td key={`${c}i`} className="num">{kwacha(p.months.reduce((a, m) => a + m.channels[c].in, 0))}</td>,
              <td key={`${c}o`} className="num">{kwacha(p.months.reduce((a, m) => a + m.channels[c].out, 0))}</td>,
              <td key={`${c}b`} />])}
            <td className="num">{kwacha(t.in)}</td><td className="num">{kwacha(t.out)}</td><td className="num">{kwacha(t.net)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}
