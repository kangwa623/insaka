"""How well the Qwen labeller and the keyword-rules baseline label transactions.

    python -m insaka.evaluation.labelling --data data/synthetic

Runs on the ground-truth CSVs (the parser reproduces them exactly, see the parsing
evaluation) for Mwila plus a sample of clients stratified by business type. The sample
always includes the prompt-injection clients and some tampered statements. Results go to
data/evaluation/labelling.json for the Evaluation screen.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

from ..generator import MWILA_ID
from ..labelling import label_case
from ..ledger import LedgerRow, Statement

SAMPLE_SEED = 7


def load_statement(data_dir: Path, client: dict, channel: str) -> tuple[Statement, dict]:
    """One statement rebuilt from its ground-truth CSV, plus truth per row_id."""
    path = Path(data_dir) / "transactions" / f"{client['client_id']}_{channel}.csv"
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    statement = Statement(
        statement_id=f"{client['client_id']}-{channel.upper()}", channel=channel,
        holder=client["owner_name"], business=client["business_name"],
        account=client["channels"][channel], period="", opening_balance=0.0,
        closing_balance=0.0, source_file=str(path))
    truth = {}
    for r in rows:
        statement.rows.append(LedgerRow(
            row_id=r["row_id"], channel=channel, date=r["date"], time=r["time"],
            description=r["description"], reference=r["reference"],
            direction=r["direction"], amount=float(r["amount"]),
            balance=float(r["balance"]), page=0))
        truth[r["row_id"]] = {"category": r["true_category"],
                              "injection": r["injection"] == "True"}
    return statement, truth


def load_case(data_dir: Path, client: dict) -> tuple[list[Statement], dict]:
    """A client's statements rebuilt from the ground-truth CSVs, plus truth per row_id."""
    statements, truth = [], {}
    for channel in client["channels"]:
        statement, rows = load_statement(data_dir, client, channel)
        statements.append(statement)
        truth.update(rows)
    return statements, truth


def sample_clients(clients: list[dict], truth: dict, n: int, seed: int = SAMPLE_SEED) -> list[str]:
    """Mwila, every injection client, two tampered clients, then round-robin by business type."""
    rng = np.random.default_rng(seed)
    others = [c for c in clients if c["client_id"] != MWILA_ID]
    chosen = [c["client_id"] for c in others if truth[c["client_id"]]["injection_rows"]]
    tampered = [c["client_id"] for c in others
                if truth[c["client_id"]]["tamper"] and c["client_id"] not in chosen]
    chosen += [str(c) for c in rng.choice(tampered, size=min(2, len(tampered)), replace=False)]
    return [MWILA_ID] + _round_robin(others, chosen, n, rng)


def holdout_clients(clients: list[dict], truth: dict, n: int) -> list[str]:
    """n clients outside the main sample, which the prompt was tuned on, for an honest score."""
    used = set(sample_clients(clients, truth, n))
    rest = [c for c in clients if c["client_id"] not in used]
    return _round_robin(rest, [], n, np.random.default_rng(SAMPLE_SEED + 1))


def _round_robin(clients: list[dict], chosen: list[str], n: int, rng) -> list[str]:
    """Top chosen up to n clients, taking one business type at a time."""
    by_type = defaultdict(list)
    for c in clients:
        if c["client_id"] not in chosen:
            by_type[c["archetype"]].append(c["client_id"])
    for ids in by_type.values():
        rng.shuffle(ids)
    types = sorted(by_type)
    while len(chosen) < n and any(by_type.values()):
        for t in types:
            if by_type[t] and len(chosen) < n:
                chosen.append(by_type[t].pop())
    return chosen


def scores(y_true: list, y_pred: list) -> dict:
    labels = sorted(set(y_true))
    p, r, f, support = precision_recall_fscore_support(y_true, y_pred, labels=labels,
                                                       zero_division=0)
    return {
        "rows": len(y_true),
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "per_category": {c: {"precision": p[i], "recall": r[i], "f1": f[i], "support": int(support[i])}
                         for i, c in enumerate(labels)},
    }


def bootstrap_ci(per_client: dict, n_boot: int = 1000, seed: int = 0) -> dict:
    """95% interval for accuracy and macro-F1, resampling whole clients.

    Each client's confusion matrix is computed once; a resample just sums them.
    """
    rng = np.random.default_rng(seed)
    ids = sorted(per_client)
    labels = sorted({x for t, p in per_client.values() for x in t + p})
    matrices = np.stack([confusion_matrix(*per_client[c], labels=labels) for c in ids])
    acc, f1 = [], []
    for _ in range(n_boot):
        m = matrices[rng.integers(len(ids), size=len(ids))].sum(axis=0)
        tp, true_n, pred_n = np.diag(m), m.sum(axis=1), m.sum(axis=0)
        present = true_n > 0
        f = np.divide(2 * tp, true_n + pred_n, out=np.zeros(len(labels)), where=true_n + pred_n > 0)
        acc.append(tp.sum() / m.sum())
        f1.append(f[present].mean())
    return {"accuracy": [float(np.percentile(acc, 2.5)), float(np.percentile(acc, 97.5))],
            "macro_f1": [float(np.percentile(f1, 2.5)), float(np.percentile(f1, 97.5))]}


def evaluate(data_dir: str | Path, n_clients: int = 20, methods=("rules", "llm"),
             labeller=None, holdout: bool = False) -> dict:
    data_dir = Path(data_dir)
    clients = {c["client_id"]: c for c in json.loads((data_dir / "clients.json").read_text("utf-8"))}
    truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))
    pick = holdout_clients if holdout else sample_clients
    sample = pick(list(clients.values()), truth, n_clients)
    results = {"sample": "holdout" if holdout else "main", "clients": sample}
    for method in methods:
        per_client, injection, review, stopped = {}, [], 0, None
        for cid in sample:
            statements, row_truth = load_case(data_dir, clients[cid])
            try:
                summary = label_case(statements, method, labeller)
            except Exception as e:   # e.g. the daily free-tier quota runs out mid-sample
                if method != "llm" or not per_client:
                    raise
                stopped = f"stopped at {cid}: {type(e).__name__}: {e}"
                break
            rows = [r for s in statements for r in s.rows]
            per_client[cid] = ([row_truth[r.row_id]["category"] for r in rows],
                               [r.category for r in rows])
            review += len(summary["needs_review"])
            flagged = set(summary["injection_suspected"])
            injection += [{"row_id": r.row_id, "label": r.category,
                           "classified_correctly": r.category == row_truth[r.row_id]["category"],
                           "flagged": r.row_id in flagged}
                          for r in rows if row_truth[r.row_id]["injection"]]
            false_flags = flagged - {r.row_id for r in rows if row_truth[r.row_id]["injection"]}
            injection += [{"row_id": r, "false_alarm": True} for r in sorted(false_flags)]

        y_true = [t for c in per_client.values() for t in c[0]]
        y_pred = [p for c in per_client.values() for p in c[1]]
        overall = scores(y_true, y_pred)
        labels = sorted(set(y_true) | set(y_pred))
        groups = {}
        for field in ("gender", "province"):
            by = defaultdict(lambda: ([], []))
            for cid, (t, p) in per_client.items():
                by[clients[cid][field]][0].extend(t)
                by[clients[cid][field]][1].extend(p)
            groups[field] = {g: {k: v for k, v in scores(t, p).items() if k != "per_category"}
                             for g, (t, p) in sorted(by.items())}
        results[method] = {
            "clients_labelled": len(per_client),
            **overall,
            "ci95": bootstrap_ci(per_client),
            "needs_review_rate": review / len(y_true),
            "injection_rows": injection,
            "fairness": groups,
            "confusion": {"labels": labels,
                          "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist()},
        }
        if stopped:
            results[method]["stopped"] = stopped
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/synthetic")
    parser.add_argument("--clients", type=int, default=20, help="clients besides Mwila")
    parser.add_argument("--methods", default="rules,llm")
    parser.add_argument("--holdout", action="store_true",
                        help="score on clients outside the main sample (which the prompt was tuned on)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    args.out = args.out or ("data/evaluation/labelling_holdout.json" if args.holdout
                            else "data/evaluation/labelling.json")
    results = evaluate(args.data, args.clients, tuple(args.methods.split(",")),
                       holdout=args.holdout)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2), "utf-8")
    for method in args.methods.split(","):
        r = results[method]
        print(f"{method}: {r['rows']} rows from {r['clients_labelled']} clients, "
              f"accuracy {r['accuracy']:.3f} {np.round(r['ci95']['accuracy'], 3).tolist()}, "
              f"macro-F1 {r['macro_f1']:.3f} {np.round(r['ci95']['macro_f1'], 3).tolist()}, "
              f"needs review {r['needs_review_rate']:.1%}")
        for c, s in r["per_category"].items():
            print(f"  {c:<22} P {s['precision']:.2f}  R {s['recall']:.2f}  F1 {s['f1']:.2f}  n {s['support']}")
        for i in r["injection_rows"]:
            print(f"  injection {i}")
        if "stopped" in r:
            print(f"  {r['stopped']}")
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
