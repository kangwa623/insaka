import { useEffect, useState } from "react";
import { api } from "./api.js";

// Two factors: something you know (password), then something you have (an authenticator
// app's 6-digit code). The accounts are synthetic staff; their password is shared with
// judges separately, never shown here.
export default function Login({ onSignedIn }) {
  const [accounts, setAccounts] = useState([]);
  const [username, setUsername] = useState("rm.chanda");
  const [password, setPassword] = useState("");
  const [step, setStep] = useState("password");     // password -> code
  const [ticket, setTicket] = useState(null);
  const [demoCode, setDemoCode] = useState(null);
  const [code, setCode] = useState("");
  const [enrol, setEnrol] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { api("/auth/accounts").then(setAccounts).catch((e) => setError(e.message)); }, []);

  const submitPassword = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api("/auth/login", null, { method: "POST", body: { username, password } });
      setTicket(r.mfa_ticket); setDemoCode(r.demo_code || null); setPassword(""); setStep("code");
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const submitCode = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api("/auth/mfa", null, { method: "POST", body: { mfa_ticket: ticket, code } });
      onSignedIn(r);
    } catch (err) {
      setError(err.message);
      if (/expired|Start again|locked/i.test(err.message)) { setStep("password"); setTicket(null); }
    } finally { setBusy(false); setCode(""); }
  };

  const showEnrolment = async () => {
    try { setEnrol(await api("/auth/enroll", null, { method: "POST", body: { mfa_ticket: ticket } })); }
    catch (err) { setError(err.message); }
  };

  return (
    <div className="login">
      <div className="login-card">
        <div className="login-brand">
          <span className="wordmark">Insaka</span>
          <span className="tagline">Every business has a story.</span>
        </div>
        <div className="login-body">
          <h1>{step === "password" ? "Sign in" : "Enter your authenticator code"}</h1>
          <p className="muted small-note">
            {step === "password"
              ? "Staff sign-in. Step 1 of 2: your password."
              : "Step 2 of 2: the 6-digit code from your authenticator app (Google or Microsoft Authenticator)."}
          </p>

          {step === "password" ? (
            <form onSubmit={submitPassword} className="login-form">
              <label>Account
                <select value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username">
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} · {a.roles.join(" + ")} ({a.id})</option>
                  ))}
                </select>
              </label>
              <label>Password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                       autoComplete="current-password" required maxLength={256} />
              </label>
              <button className="primary wide" disabled={busy || !password}>{busy ? "Checking…" : "Continue"}</button>
            </form>
          ) : (
            <form onSubmit={submitCode} className="login-form">
              <label>Authenticator code
                <input inputMode="numeric" pattern="[0-9 ]{6,7}" value={code} autoFocus
                       onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" required
                       placeholder="123 456" />
              </label>
              {demoCode && (
                <div className="demo-helper" role="note">
                  <b>Demo helper (prototype only):</b> the current code for this synthetic account is{" "}
                  <code>{demoCode.slice(0, 3)} {demoCode.slice(3)}</code>. A real deployment turns this off.
                </div>
              )}
              <button className="primary wide" disabled={busy || code.replace(/\s/g, "").length !== 6}>
                {busy ? "Verifying…" : "Sign in"}
              </button>
              {!enrol ? (
                <button type="button" className="link" onClick={showEnrolment}>Set up an authenticator app</button>
              ) : (
                <div className="enrol">
                  <img src={enrol.qr} alt="QR code to add this account to an authenticator app" width="180" height="180" />
                  <div>
                    <p className="small-note">Scan with Google or Microsoft Authenticator, or enter this key:</p>
                    <code className="secret">{enrol.secret.match(/.{1,4}/g).join(" ")}</code>
                  </div>
                </div>
              )}
              <button type="button" className="link" onClick={() => { setStep("password"); setTicket(null); setEnrol(null); }}>
                Use a different account
              </button>
            </form>
          )}
          {error && <div className="phone-error" role="alert">{error}</div>}
          <p className="muted tiny">
            Synthetic data only. Sessions end after 30 minutes or when the tab closes. Five wrong
            attempts lock an account for 15 minutes. Every sign-in is logged.
          </p>
        </div>
      </div>
    </div>
  );
}
