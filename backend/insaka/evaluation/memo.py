"""Are memo figures right, and does every one have a source?

    python -m insaka.evaluation.memo

For every demo client the memo is drafted from the generator's categories with the fixed
template (no model call); Mwila's committed Qwen-written memo is checked too. For each
figure shown in a memo:
- accuracy: the text shown equals the computed value, formatted; for figures that are a
  sum of statement lines, those lines are re-added and must give the same value;
- traceability: it links to statement rows, or says it comes from the application or
  the risk model;
and across the memo text outside those figures, no digit may appear (unsupported
numbers). Writes data/evaluation/memo.json.
"""

import argparse
import json
import re
from pathlib import Path

from ..agent.tools import NoChat
from ..features import Figure
from ..memo import assess, draft, fmt
from ..scoring import model as risk
from ..scoring.cohort import prepare_case

SUMMED = ("peak_month_income",)   # figures whose value is the sum of their rows


def check_memo(sections: list[dict], figures: dict, ledger: dict | None = None,
               corrections: dict | None = None) -> dict:
    """corrections: balance-implied amounts for rows the tamper check caught, as the features use."""
    corrections = corrections or {}
    shown = linked = right = unsupported = 0
    problems = []
    for s in sections:
        bare = s["text"]
        for span in s["figures"]:
            shown += 1
            fig = figures[span["figure"]]
            expected = fmt(fig)
            ok = span["text"] in (expected, expected.rstrip("x"))
            if ok and ledger is not None and fig.name in SUMMED:
                total = sum(corrections.get(r, ledger[r].amount) for r in fig.rows)
                ok = abs(total - fig.value) < 0.01
            right += ok
            if not ok:
                problems.append(f"{s['title']}: {span['figure']} shows {span['text']}, computed {expected}")
            linked += bool(span["rows"]) or span["source"] in ("application", "risk model")
            bare = bare.replace(span["text"], "", 1)
        stray = re.findall(r"\d[\d,.]*", bare)
        unsupported += len(stray)
        problems += [f"{s['title']}: number without a source {n!r}" for n in stray]
    return {"figures_shown": shown, "correct": right, "linked": linked,
            "unsupported_numbers": unsupported, "problems": problems}


def evaluate(data_dir="data/synthetic", cases_dir="data/cases") -> dict:
    data_dir = Path(data_dir)
    clients = json.loads((data_dir / "clients.json").read_text("utf-8"))
    truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))
    bundle = risk.load()
    totals = {"memos": 0, "figures_shown": 0, "correct": 0, "linked": 0, "unsupported_numbers": 0}
    problems = {}
    for client in clients:
        cid = client["client_id"]
        statements, report, corrections = prepare_case(data_dir, client, truth[cid], "truth")
        case = assess(statements, report, client, bundle)
        memo = draft(case, {}, chat=NoChat(), cache_dir=Path(cases_dir) / "_unused")
        ledger = {r.row_id: r for s in statements for r in s.rows}
        result = check_memo(memo["sections"], case["figures"], ledger, corrections)
        totals["memos"] += 1
        for k in ("figures_shown", "correct", "linked", "unsupported_numbers"):
            totals[k] += result[k]
        if result["problems"]:
            problems[cid] = result["problems"]

    qwen = None
    path = Path(cases_dir) / "MWILA-001.json"
    if path.exists():
        data = json.loads(path.read_text("utf-8"))
        figures = {k: Figure(**v) for k, v in data["figures"].items()}
        qwen = {"client_id": "MWILA-001", "written_by": data["memo"]["written_by"],
                **check_memo(data["memo"]["sections"], figures)}

    return {
        "template_memos": {**totals,
                           "accuracy": totals["correct"] / totals["figures_shown"],
                           "traceability": totals["linked"] / totals["figures_shown"],
                           "problems": problems},
        "mwila_model_memo": qwen,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/synthetic")
    parser.add_argument("--out", default="data/evaluation/memo.json")
    args = parser.parse_args()
    r = evaluate(args.data)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(r, indent=2), "utf-8")
    t = r["template_memos"]
    print(f"{t['memos']} memos, {t['figures_shown']} figures: accuracy {t['accuracy']:.1%}, "
          f"traceability {t['traceability']:.1%}, numbers without a source {t['unsupported_numbers']}")
    for cid, p in list(t["problems"].items())[:5]:
        print(f"  {cid}: {p[:3]}")
    if r["mwila_model_memo"]:
        m = r["mwila_model_memo"]
        print(f"Mwila ({m['written_by']}): {m['figures_shown']} figures, {m['correct']} correct, "
              f"{m['linked']} linked, {m['unsupported_numbers']} without a source {m['problems'][:3]}")
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
