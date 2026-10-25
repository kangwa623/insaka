"""The Insaka API and local app server.

    python -m insaka.api            # http://127.0.0.1:5000

Sign-in is simulated: the screens send the chosen staff member in the X-User header. Every
action still goes through insaka.case, which checks that user's role (and maker-checker)
on the server, so hiding a button in the screens is never the only control.
"""

import json
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from .case import USERS, NotAllowed, load_case, load_ledger

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
               evaluation_dir="data/evaluation", **agent_settings) -> Flask:
    app = Flask(__name__, static_folder=None)
    data_dir, cases_dir, evaluation_dir = Path(data_dir), Path(cases_dir), Path(evaluation_dir)

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
        run_case(cid, mode, data_dir, cases_dir=cases_dir, agent_dir=agent_dir, **agent_settings)
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
