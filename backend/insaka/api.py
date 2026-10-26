"""The Insaka API and local app server.

    python -m insaka.api            # http://127.0.0.1:5000

Sign-in is simulated: the screens send the chosen staff member in the X-User header. Every
action still goes through insaka.case, which checks that user's role (and maker-checker)
on the server, so hiding a button in the screens is never the only control.
"""

import json
import os
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from .agent.tools import upload_token
from .case import USERS, NotAllowed, load_case, load_ledger
from .uploads import CONSENTS, UploadRejected, accept_statement, load_record, record_consent

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
EVALUATIONS = ("parsing", "labelling", "labelling_holdout", "scoring", "memo", "agent")


def _finite(o):
    """NaN (e.g. AUROC for a group with no defaults) is not valid JSON; send null."""
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_finite(v) for v in o]
    return o


def create_app(data_dir="data/synthetic", cases_dir="data/cases", agent_dir="data/agent",
               evaluation_dir="data/evaluation", uploads_dir="data/uploads", **agent_settings) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    # The screens are served from Firebase and call this API on Render: allow those origins
    # (INSAKA_CORS_ORIGINS, comma-separated); with none set, as in local use, allow any.
    origins = {o.strip() for o in os.environ.get("INSAKA_CORS_ORIGINS", "").split(",") if o.strip()}

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        if origin and (not origins or origin in origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-User"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "3600"
        return response
    data_dir, cases_dir, evaluation_dir = Path(data_dir), Path(cases_dir), Path(evaluation_dir)
    uploads_dir = Path(uploads_dir)

    def clients() -> dict:
        return {c["client_id"]: c for c in
                json.loads((data_dir / "clients.json").read_text("utf-8"))}

    def user() -> str:
        u = request.headers.get("X-User", "")
        if u not in USERS:
            abort(401, description="choose a staff member to sign in as")
        return u

    def case_or_404(cid: str):
        if not (cases_dir / f"{cid}.json").exists():
            abort(404, description=f"no case prepared for {cid} yet")
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
        return {"token": upload_token(cid), "link": f"/upload/{upload_token(cid)}",
                "consent": record["consent"], "statements": listed}

    @app.errorhandler(UploadRejected)
    def rejected(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(NotAllowed)
    def not_allowed(e):
        return jsonify(error=str(e)), 403

    @app.errorhandler(401)
    @app.errorhandler(404)
    def http_error(e):
        return jsonify(error=e.description), e.code

    @app.get("/api/users")
    def users():
        return jsonify([{"id": k, **v} for k, v in USERS.items()])

    @app.get("/api/cases")
    def list_cases():
        user()
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
                         "band": score.get("band"), "pd": score.get("pd"),
                         "escalations": len(data.get("escalations", [])),
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
    def get_case(cid):
        u = user()
        client = clients().get(cid) or abort(404, description=f"no client {cid}")
        if not (cases_dir / f"{cid}.json").exists():
            return jsonify(client=client, case=None, audit=[])
        view = load_case(cid, cases_dir).view(u)
        return jsonify(client=client, **view)

    @app.get("/api/evaluation")
    def evaluation():
        """Every evaluation result, as measured; a missing file comes back as null."""
        user()
        out = {}
        for name in EVALUATIONS:
            path = evaluation_dir / f"{name}.json"
            out[name] = _finite(json.loads(path.read_text("utf-8"))) if path.exists() else None
        return jsonify(out)

    @app.get("/api/cases/<cid>/ledger")
    def ledger(cid):
        user()
        return jsonify(load_ledger(cid, cases_dir))

    @app.get("/api/cases/<cid>/brief")
    def brief(cid):
        user()
        case = case_or_404(cid)
        from .brief import build_brief
        return jsonify(build_brief(case.data, load_ledger(cid, cases_dir), clients()[cid]))

    @app.get("/api/cases/<cid>/documents")
    def case_documents(cid):
        user()
        if cid not in clients():
            abort(404, description=f"no client {cid}")
        return jsonify(documents(cid))

    @app.post("/api/cases/<cid>/upload")
    def rm_upload(cid):
        u = user()
        if "rm" not in USERS[u]["roles"]:
            raise NotAllowed(f"{u} cannot upload statements; RMs do")
        client = clients().get(cid) or abort(404, description=f"no client {cid}")
        channel = request.form.get("channel", "")
        f = request.files.get("file")
        summary = accept_statement(client, channel, f.read() if f else b"", u, uploads_dir)
        audit_if_case(cid, u, "upload_statement", summary)
        return jsonify(documents(cid))

    # The customer's secure link: no staff sign-in, the token identifies the application.
    def client_for_token(token: str) -> dict:
        found = next((c for c in clients().values() if upload_token(c["client_id"]) == token), None)
        if not found:
            abort(404, description="This link is not valid. Ask your relationship manager for a new one.")
        return found

    @app.get("/api/upload/<token>")
    def upload_info(token):
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
        return jsonify(accepted=accepted, uploaded=sorted(load_record(cid, uploads_dir)["files"]))

    @app.get("/api/cases/<cid>/pamodzi")
    def pamodzi(cid):
        user()
        case_or_404(cid)
        from .pamodzi import monthly_flows
        return jsonify(monthly_flows(load_ledger(cid, cases_dir)))

    @app.post("/api/cases/<cid>/run")
    def run(cid):
        u = user()
        if "rm" not in USERS[u]["roles"]:
            raise NotAllowed(f"{u} cannot start a case; RMs do")
        if cid not in clients():
            abort(404, description=f"no client {cid}")
        existing = cases_dir / f"{cid}.json"
        if existing.exists() and load_case(cid, cases_dir).status not in ("awaiting_rm", "escalated"):
            raise NotAllowed("this case is already with people; it cannot be re-run")
        from .agent import run_case
        mode = (request.get_json(silent=True) or {}).get("mode", "llm")
        run_case(cid, mode, data_dir, cases_dir=cases_dir, agent_dir=agent_dir,
                 uploads_dir=uploads_dir, **agent_settings)
        return jsonify(client=clients()[cid], **load_case(cid, cases_dir).view(u))

    def act(cid, fn):
        u = user()
        case = case_or_404(cid)
        body = request.get_json(silent=True) or {}
        result = fn(case, u, body)
        return jsonify(client=clients()[cid], result=result, **case.view(u))

    @app.post("/api/cases/<cid>/edit")
    def edit(cid):
        return act(cid, lambda c, u, b: c.rm_edit(u, b.get("section", ""), b.get("text", "")))

    @app.post("/api/cases/<cid>/submit")
    def submit(cid):
        return act(cid, lambda c, u, b: c.rm_submit(u, b.get("note", "")))

    @app.post("/api/cases/<cid>/decide")
    def decide(cid):
        return act(cid, lambda c, u, b: c.approver_decide(u, b.get("decision", ""), b.get("note", "")))

    @app.post("/api/cases/<cid>/disburse")
    def disburse(cid):
        return act(cid, lambda c, u, b: c.disburse(u))

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path):
        if not FRONTEND.exists():
            return ("The screens are not built yet: run `npm install` and `npm run build` "
                    "in frontend/.", 503)
        target = FRONTEND / path
        if path and target.is_file():
            return send_from_directory(FRONTEND, path)
        return send_from_directory(FRONTEND, "index.html")

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Insaka app locally.")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
