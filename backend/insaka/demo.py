"""Put a handful of demo cases at different stages, so the pipeline board has a pipeline.

    python -m insaka.demo --seed

Prepares a few clients with the rules agent (cached labels, template memo: no model
calls) and moves them through the workflow as the synthetic staff would, through the
same role checks as the app. Mwila's case is left as it is. Seeded case files are not
committed; run this again after a fresh clone.
"""

import argparse
import json
from pathlib import Path

from .agent import NoChat, run_case
from .agent.mocks import load_registry

# (stage, actions) applied in order to the chosen clients
PLAN = [
    ("awaiting_rm", []),
    ("awaiting_rm", []),
    ("submitted", [("rm_submit", "rm.chanda", "Steady takings; please review.")]),
    ("submitted", [("rm_submit", "rm.mutale", "")]),
    ("approved", [("rm_submit", "rm.chanda", ""),
                  ("approver_decide", "approver.banda", "approved",
                   "Surplus covers the instalment comfortably.")]),
    ("disbursed", [("rm_submit", "rm.mutale", ""),
                   ("approver_decide", "approver.banda", "approved",
                    "Seasonal income, predictable; covered by the harvest."),
                   ("disburse", "approver.banda")]),
    ("declined", [("rm_submit", "rm.chanda", ""),
                  ("approver_decide", "approver.banda", "declined",
                   "Overdraft most days and one customer dominates; revisit in six months.")]),
]


def pick_clients(data_dir: Path, labels_dir: Path = Path("data/labels")) -> tuple[list[str], str | None]:
    clients = json.loads((data_dir / "clients.json").read_text("utf-8"))
    truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))
    registry = load_registry()
    planted = set(registry.get("pacra_not_found", [])) | set(registry.get("zra_no_record", []))
    cached = {p.stem for p in labels_dir.glob("*.json")}
    plain = [c["client_id"] for c in clients
             if c["client_id"] != "MWILA-001" and c["client_id"] in cached
             and c["client_id"] not in planted and not truth[c["client_id"]]["tamper"]
             and not truth[c["client_id"]]["injection_rows"]]
    stopped = next((c for c in registry.get("pacra_not_found", []) if c in cached), None)
    return plain[:len(PLAN)], stopped


def seed(data_dir="data/synthetic", cases_dir="data/cases", **settings) -> dict:
    data_dir = Path(data_dir)
    settings = {"memo_chat": NoChat(), **settings}
    chosen, stopped = pick_clients(data_dir)
    done = {}
    for i, (cid, (stage, actions)) in enumerate(zip(chosen, PLAN)):
        # The case belongs to the RM who submits it (or alternates when nobody has yet).
        rm = next((u for name, u, *_ in actions if name == "rm_submit"),
                  ("rm.chanda", "rm.mutale")[i % 2])
        _, _, case = run_case(cid, "rules", data_dir, cases_dir=cases_dir, assigned_rm=rm, **settings)
        for name, user, *args in actions:
            getattr(case, name)(user, *args)
        done[cid] = case.status
    if stopped:
        _, _, case = run_case(stopped, "rules", data_dir, cases_dir=cases_dir, **settings)
        done[stopped] = case.status
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", action="store_true", required=True)
    args = parser.parse_args()
    for cid, status in seed().items():
        print(f"{cid}: {status}")


if __name__ == "__main__":
    main()
