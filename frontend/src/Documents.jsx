import { useEffect, useState } from "react";
import { CHANNELS } from "./api.js";

const SOURCE = { absa_internal: "Held internally", uploaded: "Uploaded", requested: "Requested" };

// Where each statement came from, the customer's secure link and consent, and an RM upload.
export default function Documents({ cid, user, me, notify }) {
  const [d, setD] = useState(null);
  const [channel, setChannel] = useState("absa");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setD(null); fetch(`/api/cases/${cid}/documents`, { headers: { "X-User": user } }).then((r) => r.json()).then(setD); }, [cid, user]);
  if (!d || d.error) return null;
  const link = `${window.location.origin}${d.link}`;

  const upload = async () => {
    setBusy(true);
    const form = new FormData();
    form.append("channel", channel);
    form.append("file", file);
    try {
      const r = await fetch(`/api/cases/${cid}/upload`, { method: "POST", headers: { "X-User": user }, body: form });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error);
      setD(data); setFile(null);
      notify("Statement checked and saved; prepare the case again to use it", "ok");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card documents">
      <div className="doc-list">
        {d.statements.map((s) => (
          <span key={s.channel} className={`doc doc-${s.source}`}>
            <b>{CHANNELS[s.channel]}</b> {s.account} · {SOURCE[s.source]}
            {s.upload && <small> ({s.upload.rows} rows, by {s.upload.by})</small>}
          </span>
        ))}
        <span className={`doc ${d.consent ? "doc-uploaded" : "doc-requested"}`}>
          {d.consent ? `✓ Customer consent ${new Date(d.consent.at).toLocaleDateString()}` : "No customer consent yet"}
        </span>
      </div>
      <div className="doc-actions">
        <span className="muted">Customer's secure link:</span>
        <a href={d.link} target="_blank" rel="noreferrer">{d.link}</a>
        <button className="link" onClick={() => { navigator.clipboard?.writeText(link); notify("Link copied", "ok"); }}>Copy</button>
        {me?.roles.includes("rm") && (
          <span className="rm-upload">
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              {d.statements.map((s) => <option key={s.channel} value={s.channel}>{CHANNELS[s.channel]}</option>)}
            </select>
            <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files[0])} />
            <button className="secondary" disabled={!file || busy} onClick={upload}>{busy ? "Checking…" : "Upload statement"}</button>
          </span>
        )}
      </div>
    </section>
  );
}
