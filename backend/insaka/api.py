"""The Insaka API and local app server.

    python -m insaka.api            # http://127.0.0.1:5000

Staff sign in with a password and an authenticator code (see insaka.auth) and send the
signed access token as "Authorization: Bearer ...". Every route is deny-by-default: it
names the roles it allows, and insaka.case enforces the finer rules (the case's own RM,
maker-checker, delegated limits). Hiding a button in the screens is never the only control.
Security events go to a hash-chained log; errors never expose internals.
"""

import json
import logging
import os
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .auth import (AuthError, Authenticator, client_for_upload_token, demo_helper_on,
                   upload_token, using_dev_secrets)
from .case import APPROVAL_LIMITS, ESCALATE_TO, USERS, NotAllowed, case_lock, load_case, load_ledger
from .security import (MODEL_BREAKER, MODEL_BUDGET, SECURITY_HEADERS, EventLog, RateLimiter,
                       valid_client_id)
from .uploads import CONSENTS, UploadRejected, accept_statement, load_record, record_consent

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
EVALUATIONS = ("parsing", "labelling", "labelling_holdout", "scoring", "memo", "agent")
ANY_STAFF = ("rm", "approver", "manager", "auditor")
LIVE_RUNS_PER_HOUR = 5

log = logging.getLogger("insaka.api")


def _finite(o):
    """NaN (e.g. AUROC for a group with no defaults) is not valid JSON; send null."""
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_finite(v) for v in o]
    return o


AUTH_MESSAGES = {
    "invalid": (401, "Wrong username or password."),
    "code": (401, "That code is not right. Check your authenticator and try again."),
    "replay": (401, "That code has already been used. Wait for the next one."),
    "ticket": (401, "The sign-in step expired. Start again."),
    "locked": (423, "Too many failed attempts. This account is locked for 15 minutes."),
    "locked_now": (423, "Too many failed attempts. This account is now locked for 15 minutes."),
    "expired": (401, "Your session has expired. Sign in again."),
    "invalid_token": (401, "Sign in to continue."),
    "revoked": (401, "You have signed out. Sign in again."),
}


def create_app(data_dir="data/synthetic", cases_dir="data/cases", agent_dir="data/agent",
               evaluation_dir="data/evaluation", uploads_dir="data/uploads", frontend_dir=FRONTEND,
               security_dir="data/security", **agent_settings) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    data_dir, cases_dir, evaluation_dir = Path(data_dir), Path(cases_dir), Path(evaluation_dir)
    uploads_dir, frontend_dir = Path(uploads_dir), Path(frontend_dir)
    site_url = os.environ.get("INSAKA_SITE_URL", "https://insaka.web.app").rstrip("/")
    # The screens are served from Firebase and call this API on Render: allow those origins
    # (INSAKA_CORS_ORIGINS, comma-separated); with none set, as in local use, allow any.
    origins = {o.strip() for o in os.environ.get("INSAKA_CORS_ORIGINS", "").split(",") if o.strip()}
    auth = Authenticator()
    events = EventLog(Path(security_dir) / "events.jsonl")
    limiter = RateLimiter()
    started = time.time()
    app.extensions["insaka"] = {"auth": auth, "events": events, "limiter": limiter}

    # --- request plumbing ------------------------------------------------------------
    def ip() -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() or request.remote_addr or "-"

    @app.before_request
    def tag_request():
        g.request_id = secrets.token_hex(6)
        g.user = None

    @app.after_request
    def headers(response):
        origin = request.headers.get("Origin")
        if origin and (not origins or origin in origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "3600"
        if request.path.startswith("/api/"):
            response.headers.update(SECURITY_HEADERS)
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Id"] = g.get("request_id", "-")
        return response

    def security_event(event, severity="info", **details):
        events.record(event, user=g.get("user"), ip=ip(), severity=severity,
                      request_id=g.get("request_id"), path=request.path, **details)

    # --- errors: a clear message, never a stack trace ----------------------------------
    @app.errorhandler(UploadRejected)
    def rejected(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(NotAllowed)
    def not_allowed(e):
        security_event("access_denied", "warning", reason=str(e))
        return jsonify(error=str(e)), 403

    @app.errorhandler(HTTPException)
    def http_error(e):
        if e.code == 403:
            security_event("access_denied", "warning", reason=e.description)
        elif e.code == 401 and request.headers.get("Authorization"):
            # A token was presented and rejected (forged, expired, revoked); a plain visit
            # to the sign-in page is not an event.
            security_event("token_rejected", "warning", reason=e.description)
        return jsonify(error=e.description), e.code

    @app.errorhandler(Exception)
    def unexpected(e):
        log.exception("request %s failed", g.get("request_id"))
        security_event("server_error", "error", kind=type(e).__name__)
        return jsonify(error="Something went wrong on our side. It has been logged.",
                       request_id=g.get("request_id")), 500

    # --- who is calling ------------------------------------------------------------------
    def current_user() -> str:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            abort(401, description="Sign in to continue.")
        try:
            g.user, g.sid = auth.verify(header[7:].strip())
        except AuthError as e:
            abort(401, description=AUTH_MESSAGES[str(e)][1])
        return g.user

    def requires(*roles):
        """Deny by default: the route runs only for a signed-in user holding one of roles."""
        def wrap(fn):
            @wraps(fn)
            def inner(*args, **kwargs):
                u = current_user()
                if not set(USERS[u]["roles"]) & set(roles):
                    raise NotAllowed(f"{u} does not have access to this")
                if "cid" in kwargs and not valid_client_id(kwargs["cid"]):
                    abort(404, description="No such client.")
                return fn(u, *args, **kwargs)
            return inner
        return wrap

    def limited(key: str, limit: int, window_s: float) -> None:
        if not limiter.allow(key, limit, window_s):
            security_event("rate_limited", "warning", key=key.split(":")[0])
            abort(429, description="Too many requests. Wait a minute and try again.")

    # --- data helpers ----------------------------------------------------------------------
    def clients() -> dict:
        return {c["client_id"]: c for c in
                json.loads((data_dir / "clients.json").read_text("utf-8"))}

    def case_or_404(cid: str):
        if not (cases_dir / f"{cid}.json").exists():
            abort(404, description=f"No case prepared for {cid} yet.")
        return load_case(cid, cases_dir)

    def audit_if_case(cid: str, who: str, action: str, details: dict) -> None:
        if (cases_dir / f"{cid}.json").exists():
            case = load_case(cid, cases_dir)
            case._audit(who, action, case.status, details)

    def documents(cid: str) -> dict:
        client = clients()[cid]
        record = load_record(cid, uploads_dir)
        listed = []
        for ch, account in client["channels"].items():
            uploaded = record["files"].get(ch)
            source = ("uploaded" if uploaded else "absa_internal" if ch == "absa" else "requested")
            listed.append({"channel": ch, "account": account, "source": source, "upload": uploaded})
        token = upload_token(cid)
        return {"link": f"/upload/{token}", "link_expires_in_days": 7,
                "consent": record["consent"], "statements": listed}

    # --- sign-in -------------------------------------------------------------------------
    @app.get("/api/auth/accounts")
    def accounts():
        """Who can sign in (synthetic staff): names and roles only, never secrets."""
        return jsonify([{"id": k, "name": v["name"], "roles": v["roles"],
                         "approval_limit": APPROVAL_LIMITS.get(k)} for k, v in USERS.items()])

    @app.post("/api/auth/login")
    def login():
        limited(f"login:{ip()}", 10, 60)
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", ""))[:64]
        try:
            out = auth.check_password(username, str(body.get("password", ""))[:256])
        except AuthError as e:
            security_event("login_failed" if "locked" not in str(e) else "account_locked",
                           "warning", username=username)
            status, message = AUTH_MESSAGES[str(e)]
            return jsonify(error=message), status
        security_event("password_ok", username=username)
        return jsonify(out)

    @app.post("/api/auth/enroll")
    def enroll():
        limited(f"mfa:{ip()}", 10, 60)
        body = request.get_json(silent=True) or {}
        try:
            info = auth.enrolment(str(body.get("mfa_ticket", "")))
        except AuthError as e:
            status, message = AUTH_MESSAGES[str(e)]
            return jsonify(error=message), status
        import segno
        qr = segno.make(info["uri"], error="m")
        return jsonify(secret=info["secret"], uri=info["uri"],
                       qr=qr.svg_data_uri(scale=5, dark="#1a1416", light="#ffffff"))

    @app.post("/api/auth/mfa")
    def mfa():
        limited(f"mfa:{ip()}", 10, 60)
        body = request.get_json(silent=True) or {}
        ticket = str(body.get("mfa_ticket", ""))
        try:
            out = auth.check_code(ticket, str(body.get("code", ""))[:12])
        except AuthError as e:
            security_event("mfa_failed" if "locked" not in str(e) else "account_locked",
                           "warning", reason=str(e))
            status, message = AUTH_MESSAGES[str(e)]
            return jsonify(error=message), status
        g.user = out["user"]["id"]
        security_event("signed_in")
        return jsonify(out)

    @app.post("/api/auth/logout")
    @requires(*ANY_STAFF)
    def logout(u):
        auth.revoke(g.sid)
        security_event("signed_out")
        return jsonify(ok=True)

    @app.get("/api/auth/me")
    @requires(*ANY_STAFF)
    def me(u):
        return jsonify(id=u, **USERS[u], approval_limit=APPROVAL_LIMITS.get(u))

    # --- reliability -----------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        """For uptime checks and the screens' banners. No case data."""
        from .scoring.model import MODEL_PATH, verify
        checks = {"data": (data_dir / "clients.json").exists(),
                  "risk_model_verified": MODEL_PATH.exists() and verify(MODEL_PATH),
                  "event_log_intact": events.verify()["intact"]}
        model = {"configured": bool(os.environ.get("GROQ_API_KEY")), **MODEL_BREAKER.state(),
                 "budget": MODEL_BUDGET.state()}
        ai = "available" if model["configured"] and model["state"] == "closed" \
            and model["budget"]["used_today"] < model["budget"]["daily_limit"] else "fallback"
        return jsonify(status="ok" if all(checks.values()) else "degraded", checks=checks,
                       ai=ai, model=model, uptime_s=round(time.time() - started))

    # --- staff data ------------------------------------------------------------------------
    @app.get("/api/users")
    @requires(*ANY_STAFF)
    def users(u):
        return jsonify([{"id": k, "name": v["name"], "roles": v["roles"]} for k, v in USERS.items()])

    @app.get("/api/cases")
    @requires(*ANY_STAFF)
    def list_cases(u):
        rows = []
        for cid, c in clients().items():
            path = cases_dir / f"{cid}.json"
            data = json.loads(path.read_text("utf-8")) if path.exists() else {}
            score = data.get("score") or {}
            steps = (data.get("agent_run") or {}).get("steps") or []
            audit = cases_dir / f"{cid}.audit.jsonl"
            last = audit.read_text("utf-8").strip().splitlines()[-1] if audit.exists() else None
            rows.append({"client_id": cid, "business_name": c["business_name"],
                         "business_type": c["business_type"], "town": c["town"],
                         "province": c["province"],
                         "requested_amount": c["application"]["requested_amount"],
                         "status": data.get("status", "not_started"),
                         "assigned_rm": data.get("assigned_rm"),
                         "band": score.get("band"), "pd": score.get("pd"),
                         "escalations": len(data.get("escalations", []))
                         + len(data.get("human_escalations", [])),
                         "stage_since": json.loads(last)["at"] if last else None,
                         "prepared_in_seconds": round(sum(s.get("ms", 0) for s in steps) / 1000, 1)
                         if steps else None,
                         "submitted_by": data.get("submitted_by"),
                         "decision": (data.get("decision") or {}).get("decision")})
        order = {"MWILA-001": 0}
        rows.sort(key=lambda r: (order.get(r["client_id"], 1), r["status"] == "not_started",
                                 r["client_id"]))
        return jsonify(rows)

    @app.get("/api/cases/<cid>")
    @requires(*ANY_STAFF)
    def get_case(u, cid):
        client = clients().get(cid) or abort(404, description="No such client.")
        if not (cases_dir / f"{cid}.json").exists():
            return jsonify(client=client, case=None, audit=[])
        return jsonify(client=client, **load_case(cid, cases_dir).view(u))

    @app.get("/api/evaluation")
    @requires(*ANY_STAFF)
    def evaluation(u):
        """Every evaluation result, as measured; a missing file comes back as null."""
        out = {}
        for name in EVALUATIONS:
            path = evaluation_dir / f"{name}.json"
            out[name] = _finite(json.loads(path.read_text("utf-8"))) if path.exists() else None
        return jsonify(out)

    @app.get("/api/cases/<cid>/ledger")
    @requires(*ANY_STAFF)
    def ledger(u, cid):
        return jsonify(load_ledger(cid, cases_dir))

    @app.get("/api/cases/<cid>/brief")
    @requires(*ANY_STAFF)
    def brief(u, cid):
        case = case_or_404(cid)
        from .brief import build_brief
        return jsonify(build_brief(case.data, load_ledger(cid, cases_dir), clients()[cid]))

    @app.get("/api/cases/<cid>/documents")
    @requires(*ANY_STAFF)
    def case_documents(u, cid):
        if cid not in clients():
            abort(404, description="No such client.")
        return jsonify(documents(cid))

    @app.get("/api/cases/<cid>/pamodzi")
    @requires(*ANY_STAFF)
    def pamodzi(u, cid):
        case_or_404(cid)
        from .pamodzi import monthly_flows
        return jsonify(monthly_flows(load_ledger(cid, cases_dir)))

    @app.post("/api/cases/<cid>/upload")
    @requires("rm")
    def rm_upload(u, cid):
        limited(f"upload:{u}", 20, 3600)
        client = clients().get(cid) or abort(404, description="No such client.")
        if (cases_dir / f"{cid}.json").exists():
            load_case(cid, cases_dir)._require_owner(u)
        channel = request.form.get("channel", "")
        f = request.files.get("file")
        summary = accept_statement(client, channel, f.read() if f else b"", u, uploads_dir)
        audit_if_case(cid, u, "upload_statement", summary)
        security_event("statement_uploaded", client=cid, channel=channel)
        return jsonify(documents(cid))

    # --- the customer's secure link: a signed, expiring token stands in for sign-in ----------
    def client_for_token(token: str) -> dict:
        cid = client_for_upload_token(token)
        found = clients().get(cid) if cid else None
        if not found:
            security_event("bad_upload_link", "warning")
            abort(404, description="This link is not valid or has expired. "
                                   "Ask your relationship manager for a new one.")
        return found

    @app.get("/api/upload/<token>")
    def upload_info(token):
        limited(f"customer:{ip()}", 30, 60)
        c = client_for_token(token)
        record = load_record(c["client_id"], uploads_dir)
        return jsonify(business_name=c["business_name"], bank="Absa Bank Zambia",
                       requested=[{"channel": ch, "account": acc} for ch, acc in c["channels"].items()
                                  if ch != "absa"],
                       consents=[{"key": k, "text": t} for k, t in CONSENTS.items()],
                       consent=record["consent"],
                       uploaded=sorted(record["files"]))

    @app.post("/api/upload/<token>")
    def customer_upload(token):
        limited(f"customer:{ip()}", 10, 60)
        c = client_for_token(token)
        cid = c["client_id"]
        consent = record_consent(cid, {k: request.form.get(k) == "true" for k in CONSENTS}, uploads_dir)
        audit_if_case(cid, "customer", "customer_consent", {"at": consent["at"]})
        accepted = []
        for ch in [ch for ch in c["channels"] if ch != "absa"]:
            f = request.files.get(ch)
            if f and f.filename:
                summary = accept_statement(c, ch, f.read(), "customer", uploads_dir)
                audit_if_case(cid, "customer", "customer_upload", summary)
                accepted.append(summary)
        security_event("customer_upload", client=cid, files=len(accepted))
        return jsonify(accepted=accepted, uploaded=sorted(load_record(cid, uploads_dir)["files"]))

    # --- the agent and the human workflow ------------------------------------------------
    @app.post("/api/cases/<cid>/run")
    @requires("rm")
    def run(u, cid):
        if cid not in clients():
            abort(404, description="No such client.")
        mode = (request.get_json(silent=True) or {}).get("mode", "llm")
        if mode not in ("llm", "rules"):
            abort(400, description="mode must be llm or rules")
        if mode == "llm":
            limited(f"run:{u}", LIVE_RUNS_PER_HOUR, 3600)
        with case_lock(cid):
            if (cases_dir / f"{cid}.json").exists():
                existing = load_case(cid, cases_dir)
                if existing.status not in ("awaiting_rm", "escalated"):
                    raise NotAllowed("this case is already with people; it cannot be re-run")
                existing._require_owner(u)
            from .agent import run_case
            result, agent_case, _ = run_case(cid, mode, data_dir, cases_dir=cases_dir,
                                             agent_dir=agent_dir, uploads_dir=uploads_dir,
                                             assigned_rm=u, **agent_settings)
        flagged = (agent_case.labelling or {}).get("injection_suspected", [])
        if flagged:
            security_event("prompt_injection_flagged", "warning", client=cid, rows=len(flagged))
        refused = [s["tool"] for s in result["steps"] if s["status"] == "refused"]
        if refused:
            security_event("agent_call_refused", "warning", client=cid, tools=refused)
        if result.get("model_fallback"):
            security_event("model_fallback", "warning", client=cid)
        return jsonify(client=clients()[cid], **load_case(cid, cases_dir).view(u))

    def act(cid, u, fn, event=None):
        with case_lock(cid):
            case = case_or_404(cid)
            body = request.get_json(silent=True) or {}
            result = fn(case, u, body)
        if event:
            security_event(event, client=cid)
        return jsonify(client=clients()[cid], result=result, **case.view(u))

    @app.post("/api/cases/<cid>/edit")
    @requires("rm")
    def edit(u, cid):
        return act(cid, u, lambda c, u, b: c.rm_edit(u, str(b.get("section", "")), str(b.get("text", ""))))

    @app.post("/api/cases/<cid>/submit")
    @requires("rm")
    def submit(u, cid):
        return act(cid, u, lambda c, u, b: c.rm_submit(u, str(b.get("note", ""))))

    @app.post("/api/cases/<cid>/decide")
    @requires("approver")
    def decide(u, cid):
        return act(cid, u, lambda c, u, b: c.approver_decide(u, str(b.get("decision", "")),
                                                            str(b.get("note", ""))), "case_decided")

    @app.post("/api/cases/<cid>/escalate")
    @requires("rm", "approver")
    def escalate(u, cid):
        return act(cid, u, lambda c, u, b: c.escalate(u, str(b.get("to", "")), str(b.get("reason", ""))),
                   "case_escalated")

    @app.post("/api/cases/<cid>/resolve")
    @requires("approver")
    def resolve(u, cid):
        return act(cid, u, lambda c, u, b: c.resolve(u, str(b.get("resolution", "")),
                                                    str(b.get("note", ""))), "escalation_resolved")

    @app.post("/api/cases/<cid>/disburse")
    @requires("rm", "approver")
    def disburse(u, cid):
        return act(cid, u, lambda c, u, b: c.disburse(u), "disbursed")

    # --- the Security screen ---------------------------------------------------------------
    @app.get("/api/security/status")
    @requires("auditor", "approver", "manager")
    def security_status(u):
        from .scoring.model import MODEL_PATH, verify
        dev = using_dev_secrets()
        return jsonify(
            mfa={"required": True, "method": "TOTP (RFC 6238)", "demo_helper": demo_helper_on()},
            sessions={"access_token_minutes": 30, "lockout_after": 5, "lockout_minutes": 15,
                      "login_rate_per_minute": 10},
            secrets={"from_environment": not any(dev.values()), "development_defaults": dev},
            cors={"restricted": bool(origins), "origins": sorted(origins)},
            approval_limits=APPROVAL_LIMITS, escalate_to=ESCALATE_TO,
            risk_model_verified=MODEL_PATH.exists() and verify(MODEL_PATH),
            model=MODEL_BREAKER.state(), budget=MODEL_BUDGET.state(),
            live_runs_per_hour=LIVE_RUNS_PER_HOUR, event_log=events.verify())

    @app.get("/api/security/events")
    @requires("auditor", "manager")
    def security_events(u):
        return jsonify(chain=events.verify(), events=events.entries()[-200:][::-1])

    # --- the built screens, when served from here ---------------------------------------
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path):
        if path.startswith("api/"):
            abort(404, description="No such endpoint.")
        if not frontend_dir.exists():
            # Deployed, the screens live on Firebase: send visitors there, keeping the path
            # so a customer's /upload/<token> link still works.
            return redirect(f"{site_url}/{path}", 302)
        target = (frontend_dir / path).resolve()
        if path and target.is_file() and frontend_dir.resolve() in target.parents:
            return send_from_directory(frontend_dir, path)
        return send_from_directory(frontend_dir, "index.html")

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Insaka app locally.")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
