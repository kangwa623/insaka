# Insaka security

Insaka is a prototype for the Absa GenAI-Thon. It runs on **synthetic data only**, and every lending decision is made by a person. This document sets out how Insaka handles security risk, organised by the **OWASP Top 10 (2025)** and the **OWASP Top 10 for LLM Applications (2025)**. For each risk it names the control, where that control lives in the code, the test that proves it, and what a bank pilot would add.

The live state of these controls is shown on the app's **Security** screen, which auditors, approvers and the manager can open.

## Threat model in brief

| What we protect | From whom | Main controls |
|---|---|---|
| Lending decisions | An insider acting alone; a manipulated AI | Maker-checker, delegated limits, escalation resolved by someone else, an agent that cannot decide |
| Customer financial data | Outsiders, curious insiders, the AI provider | MFA, roles, case ownership, masking before any AI call, signed expiring upload links, consent |
| Integrity of figures | Edited statements, tampered models, invented numbers | Balance reconciliation, transfer cross-matching, hash-checked risk model, code-inserted figures |
| Evidence of what happened | Someone covering their tracks | Append-only case audit trail and a hash-chained security event log |
| Availability | Model outages, quota exhaustion, abuse | Circuit breaker, deterministic fallbacks, token budget, rate limits |

**Who can do what**

| Role | Can | Cannot |
|---|---|---|
| RM | Prepare, edit and submit **their own** cases; upload statements; escalate | Work another RM's case; approve; read security events |
| Approver | Approve or decline **within their delegated limit**; resolve escalations; disburse after approval | Decide a case they submitted; resolve their own escalation; approve a High-risk case without a credit-risk review |
| Manager | Everything an RM and an approver can do, on any case; read security events | Bypass maker-checker |
| Auditor | Read every case, audit trail and security event | Change anything |
| Insaka agent | Read, verify, label, score, draft, escalate | Approve, decline or pay; act without giving a reason; take more than 20 steps |

## OWASP Top 10 (2025)

| Risk | Control in Insaka | Where | Proof |
|---|---|---|---|
| **A01 Broken Access Control** | Every API route is deny-by-default and names the roles it allows. Object-level checks mean only the case's assigned RM, or a manager, can change a case. Maker-checker. Delegated approval limits (K500,000 for the approver, K1,000,000 for the manager). Auditors are read-only. The server enforces all of this; the screens only reflect it. | `api.py` `requires()`, `case.py` | `test_security.py`: object-level access, maker-checker, limits; `test_api.py` |
| **A02 Security Misconfiguration** | Security headers on the API (CSP `default-src 'none'`, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, HSTS, `no-store`) and on the site (a CSP limiting scripts to the site itself and network calls to the Insaka API). CORS is limited to the Insaka site. Secrets come only from the environment. In production a missing secret is never replaced by the published development default; sign-in is then impossible until it is configured. | `security.py`, `firebase.json`, `render.yaml`, `auth.py` | `test_security.py`: headers |
| **A03 Software Supply Chain Failures** | Exact versions are pinned (`requirements.txt`, `package-lock.json`). Dependabot covers pip, npm and Actions. CI runs `pip-audit` and `npm audit`. The language model is pinned by name. **Known exception:** Pillow, which arrives through the PDF libraries, needs version 13 for current advisories, and that needs Python 3.11+. CI tests Python 3.12 with Pillow 13. The demo server stays on Python 3.10 until after the hackathon. The exposure is mitigated because Insaka only extracts text from PDFs and never decodes an uploaded image with Pillow, and uploads are PDF-only, at most 10 MB, and checked by their header. | `requirements.txt`, `.github/` | CI workflow |
| **A04 Cryptographic Failures** | HTTPS everywhere (HSTS). Passwords are stored as scrypt hashes. Tokens are signed (HMAC) and expire: 5 minutes for the MFA step, 30 minutes for a session, 7 days for a customer link. Authenticator secrets are derived from a server key and never stored. | `auth.py` | `test_auth.py`: forged, expired and revoked tokens |
| **A05 Injection** | No SQL and no shell. Client IDs must match `^(MWILA|ZM)-\d{3,4}$` before they are used in any file path. Statement text is treated as data, never as instructions. React escapes all text, and no HTML is rendered from data. | `security.valid_client_id`, `labelling/injection.py` | `test_security.py`: path traversal |
| **A06 Insecure Design** | People decide; the agent cannot approve or pay. Escalations are resolved by someone else. High-risk cases need a credit-risk review before approval. Money moves only after a recorded approval. | `case.py`, `agent/policy.py` | `test_security.py`, `test_agent.py`, `test_case.py` |
| **A07 Authentication Failures** | Multi-factor sign-in: a password, then a TOTP authenticator code (RFC 6238; Google or Microsoft Authenticator, with QR set-up). Codes cannot be replayed. Five failures lock the account for 15 minutes. Each address is limited to 10 sign-ins a minute. Error messages are generic. Sessions last 30 minutes and are revoked on sign-out. | `auth.py`, `api.py` | `test_auth.py` |
| **A08 Software or Data Integrity Failures** | The risk model loads only if its SHA-256 matches `models/risk_lr.sha256`; a joblib file can run code when loaded. Statements are tamper-checked (every balance reconciles) and transfers are cross-matched with Absa's records. The security log is hash-chained. Case files are written atomically under a per-case lock. | `scoring/model.py`, `parsing/verify.py`, `security.py` | `test_security.py`: tampered model, chain; `test_parsing.py` |
| **A09 Security Logging and Alerting Failures** | These events are recorded with the user, IP address and request ID: every sign-in, failed attempt, lockout, rejected token, refused action, rate-limit hit, escalation, decision, disbursement, prompt-injection flag, model fallback and server error. The log is append-only and hash-chained, so an edit shows up at the line where it was made. It is visible to auditors and managers. | `security.EventLog`, `api.py` | `test_security.py`: tamper-evident chain |
| **A10 Mishandling of Exceptional Conditions** | Errors return a plain message and a request ID, never a stack trace. If the model fails, a circuit breaker (3 failures in 5 minutes opens it for 5 minutes) hands each case to the deterministic agent, keyword labels and the template memo, so every check still runs. The screens retry with backoff, show a banner while on fallbacks, and have an error boundary. | `api.py`, `labelling/llm.py`, `agent/loop.py`, `frontend/src/` | `test_security.py`: circuit breaker; `test_agent.py`: model outage |

## OWASP Top 10 for LLM Applications (2025)

| Risk | Control in Insaka | Where | Proof |
|---|---|---|---|
| **LLM01 Prompt Injection** | Statement text is wrapped as untrusted data. Rows that read like instructions are flagged for the RM and logged. Code refuses any tool call that breaks a rule, whatever the model says. | `labelling/injection.py`, `agent/policy.py` | `test_agent.py`: adversarial model; evaluation: all planted injection rows flagged, none obeyed |
| **LLM02 Sensitive Information Disclosure** | Names, phone numbers and account numbers are masked before any model call. The model never sees raw rows. | `labelling/masking.py` | `test_security.py`: prompts carry no personal data |
| **LLM03 Supply Chain** | An open model pinned by name, served through one provider. The scoring model is hash-checked before it loads. | `labelling/llm.py`, `scoring/model.py` | `test_security.py` |
| **LLM04 Data and Model Poisoning** | The risk model is trained offline, only on the synthetic generator. Model labels are accepted only if they quote the row they label; otherwise the row falls back to the rules and is marked for review. | `scoring/`, `labelling/llm.py` | `test_labelling.py` |
| **LLM05 Improper Output Handling** | Model output must be valid JSON naming real rows and allowed categories. Memo text may not contain its own numbers or a decision; code inserts every figure. Nothing is rendered as HTML. | `labelling/llm.py`, `memo.py` | `test_memo.py`, `test_labelling.py` |
| **LLM06 Excessive Agency** | The agent's tools are an allow-list with no approve, decline or pay tool. A 20-step limit. Every call needs a reason, which is logged. | `agent/tools.py`, `agent/policy.py` | `test_security.py`: tool allow-list |
| **LLM07 System Prompt Leakage** | Prompts contain no secrets, keys or customer data. Access control lives in code, not in the prompt, so a leaked prompt reveals nothing that matters. | `labelling/llm.py`, `agent/loop.py` | Review |
| **LLM08 Vector and Embedding Weaknesses** | **Not applicable:** Insaka uses no retrieval or embeddings. | – | – |
| **LLM09 Misinformation** | Code computes and inserts every number, and each links to its source statement rows. The evaluation found 0 unsupported numbers across 1,661 memo figures. A person reviews and decides. | `memo.py`, `features.py` | `evaluation/memo.py` |
| **LLM10 Unbounded Consumption** | Output-token caps on every call. A 20-step agent limit. 5 live agent runs per user per hour. A daily token budget (150,000 by default), after which the deterministic fallbacks take over. A 30-second timeout per call. | `security.TokenBudget`, `labelling/llm.py`, `api.py` | `test_security.py` |

## Reliability and fallbacks

| If… | Then… |
|---|---|
| The model is down, slow or out of quota | The circuit breaker opens. The rules agent, keyword labels and template memo take over. The screens show a banner and every check still runs. |
| The API is asleep (free hosting) | The screens retry with backoff and say the server is waking up. |
| Two people act on a case at once | A per-case lock and atomic writes keep the case file whole. |
| A screen fails to render | An error boundary offers a reload, and work on the server is unaffected. |
| A statement was edited | Reconciliation flags the row, its figures are marked Unverified, and the agent escalates for an RM spot-check. |

`GET /api/health` reports the data, the risk-model integrity, the event-log chain, the model's circuit state and the token budget. Render uses it as the health check.

## Prototype limits, stated plainly

- **The data is synthetic.** No real customer data is stored or sent anywhere.
- **The demo helper shows authenticator codes.** `INSAKA_DEMO_MFA_HELPER=1` shows the current code at sign-in, so judges don't need an authenticator app. The real TOTP check still runs. A pilot removes the setting.
- **The accounts are synthetic staff with one shared demo password.** It is set in the Render dashboard and shared separately. A pilot would use Absa's identity provider (Azure AD / SSO with conditional access) instead.
- **Rate limits, lockouts and revocations live in memory,** and Render's free disk resets on restart, so the security log does too. A pilot would use a shared store and ship logs to the bank's SIEM.
- **PACRA, ZRA, the credit bureau and MoMo are mocked.**
- **The Pillow exception** under A03 lasts until the demo server moves to Python 3.12.

## Reporting a problem

This is a hackathon prototype. Please report security issues to the author (see the README) rather than opening a public issue.
