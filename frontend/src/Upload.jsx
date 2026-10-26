import { useEffect, useState } from "react";

const WALLETS = { mtn: "MTN MoMo", airtel: "Airtel Money" };

// The customer's page, opened from the secure link on their phone. No staff sign-in: the
// link identifies the application. Nothing is stored without consent, and each file is
// checked against the account on the application before it is accepted.
export default function Upload({ token }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [ticks, setTicks] = useState({});
  const [files, setFiles] = useState({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    fetch(`/api/upload/${token}`).then(async (r) => {
      const d = await r.json();
      if (!r.ok) throw new Error(d.error);
      setInfo(d);
    }).catch((e) => setError(e.message));
  }, [token]);

  const submit = async () => {
    setBusy(true); setError(null);
    const form = new FormData();
    info.consents.forEach(({ key }) => form.append(key, ticks[key] ? "true" : "false"));
    Object.entries(files).forEach(([ch, f]) => f && form.append(ch, f));
    try {
      const r = await fetch(`/api/upload/${token}`, { method: "POST", body: form });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error);
      setDone(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!info) return <div className="phone"><div className="phone-card">{error || "Loading…"}</div></div>;
  const allTicked = info.consents.every(({ key }) => ticks[key]);
  const chosen = Object.values(files).some(Boolean);

  return (
    <div className="phone">
      <div className="phone-card">
        <div className="phone-brand">Insaka <span>for {info.bank}</span></div>
        {done ? (
          <>
            <h1>Thank you</h1>
            <p>Your statements were received and checked. Your relationship manager has been told.</p>
            <ul className="phone-list">{done.accepted.map((a) => (
              <li key={a.channel}>✓ {WALLETS[a.channel]}: {a.rows} transactions, {a.from} to {a.to}</li>
            ))}</ul>
          </>
        ) : (
          <>
            <h1>Share your mobile-money statements</h1>
            <p>For <b>{info.business_name}</b>'s loan application. Sharing these once lets the bank see how
              your business trades, without another branch visit.</p>
            <div className="phone-section">
              <h2>What we ask for</h2>
              {info.requested.map((r) => (
                <label key={r.channel} className="file-row">
                  <span>{WALLETS[r.channel]} statement <small>({r.account})</small>
                    {info.uploaded.includes(r.channel) && <em> received</em>}</span>
                  <input type="file" accept="application/pdf"
                         onChange={(e) => setFiles({ ...files, [r.channel]: e.target.files[0] })} />
                </label>
              ))}
              <small className="muted">Download the PDF statement from the MoMo app or USSD menu, then attach it here.</small>
            </div>
            <div className="phone-section">
              <h2>Your consent</h2>
              {info.consents.map(({ key: k, text }) => (
                <label key={k} className="consent">
                  <input type="checkbox" checked={!!ticks[k]} onChange={(e) => setTicks({ ...ticks, [k]: e.target.checked })} />
                  <span>{text}</span>
                </label>
              ))}
            </div>
            {error && <div className="phone-error">{error}</div>}
            <button className="primary wide" disabled={!allTicked || !chosen || busy} onClick={submit}>
              {busy ? "Checking…" : "Share statements"}
            </button>
            <p className="muted tiny">Your details are masked before any AI system sees them. A person at the bank makes every decision.</p>
          </>
        )}
      </div>
    </div>
  );
}
