// Calls to the Flask API. Staff sign in with a password and an authenticator code; the
// signed access token is kept for this browser tab only (sessionStorage) and sent as a
// Bearer token. The server checks the role, the case owner and the limits on every action.

// The API's address: empty for local use (Vite proxies /api); the Render URL in production.
export const API = import.meta.env.VITE_API_BASE || "";

const KEY = "insaka.session";

export const session = {
  get() {
    try { return JSON.parse(sessionStorage.getItem(KEY)); } catch { return null; }
  },
  set(s) {
    try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ }
  },
  clear() {
    try { sessionStorage.removeItem(KEY); } catch { /* private mode */ }
  },
};

export function authHeaders() {
  const s = session.get();
  return s?.token ? { Authorization: `Bearer ${s.token}` } : {};
}

const RETRY = new Set([502, 503, 504]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// GETs are retried with backoff when the server is waking up or briefly unavailable; a
// rejected sign-in (401) ends the session everywhere in the app.
export async function api(path, _user, { method = "GET", body } = {}) {
  const attempts = method === "GET" ? 3 : 1;
  for (let i = 0; i < attempts; i++) {
    let res;
    try {
      res = await fetch(`${API}/api${path}`, {
        method,
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      if (i < attempts - 1) { await sleep(1000 * 2 ** i); continue; }
      throw new Error("The server can't be reached. It may be waking up; try again in a minute.");
    }
    if (RETRY.has(res.status) && i < attempts - 1) { await sleep(1000 * 2 ** i); continue; }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && session.get()) {
      session.clear();
      window.dispatchEvent(new Event("insaka:signed-out"));
    }
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    return data;
  }
}

export const kwacha = (v) => `${v < 0 ? "−" : ""}K${Math.abs(Math.round(v)).toLocaleString("en-ZM")}`;

export const STATUS = {
  not_started: "Not started",
  preparing: "Preparing",
  awaiting_rm: "Awaiting RM review",
  escalated: "Escalated to a person",
  submitted: "With the approver",
  approved: "Approved",
  declined: "Declined",
  disbursed: "Disbursed",
};

export const TOOL_LABELS = {
  read_statement: "Read statement",
  request_documents: "Request documents",
  verify_statements: "Verify statements",
  label_transactions: "Label transactions",
  check_registration: "Check PACRA registration",
  check_tax_status: "Check ZRA tax status",
  check_credit_bureau: "Check credit bureau",
  score_risk: "Score risk",
  draft_memo: "Draft memo",
  escalate: "Escalate to the RM",
  submit_for_review: "Submit for RM review",
};

export const CATEGORY_LABELS = {
  customer_payment: "Customer payment",
  cash_deposit: "Cash deposit",
  own_account_transfer: "Own-account transfer",
  input_purchase: "Input purchase",
  wages: "Wages",
  rent: "Rent",
  utilities: "Utilities",
  airtime_data: "Airtime and data",
  family_transfer: "Family transfer",
  school_fees: "School fees",
  loan_repayment: "Loan repayment",
  tax_payment: "Tax payment",
  bank_charges: "Bank charges",
  cash_withdrawal: "Cash withdrawal",
  other: "Other",
};

export const CHANNELS = { absa: "Absa", mtn: "MTN MoMo", airtel: "Airtel Money" };

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// The same formatting the memo uses for each unit.
export function fmtFigure(fig) {
  if (fig.unit === "K") return kwacha(fig.value);
  if (fig.unit === "%") return `${Math.round(fig.value * 100)}%`;
  if (fig.unit === "x") return `${fig.value.toFixed(1)}x`;
  if (fig.unit === "month") {
    const [y, m] = String(fig.value).split("-");
    return `${MONTHS[+m - 1]} ${y}`;
  }
  return typeof fig.value === "number" && !Number.isInteger(fig.value) ? fig.value.toFixed(2) : String(fig.value);
}
