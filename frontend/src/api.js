// Calls to the Flask API. Sign-in is simulated: the chosen staff member travels in
// X-User, and the server checks that person's role on every action.

// The API's address: empty for local use (Vite proxies /api); the Render URL in production.
export const API = import.meta.env.VITE_API_BASE || "";

export async function api(path, user, { method = "GET", body } = {}) {
  const res = await fetch(`${API}/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(user ? { "X-User": user } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
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
