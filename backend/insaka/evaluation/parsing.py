"""How well the parser and tamper check do on the synthetic statements.

    python -m insaka.evaluation.parsing --data data/synthetic
"""

import argparse
import csv
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..parsing import parse_statement, verify_case

FIELDS = ("row_id", "date", "time", "description", "reference", "direction", "amount", "balance")


def _truth_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _field_matches(parsed, truth: dict, channel: str) -> dict:
    return {
        # Row ids must line up, or figures can't be traced back to ground truth.
        "row_id": parsed.row_id == truth["row_id"],
        "date": parsed.date == truth["date"],
        # Only the MTN layout prints the time of day.
        "time": parsed.time == (truth["time"] if channel == "mtn" else ""),
        "description": parsed.description == truth["description"],
        "reference": parsed.reference == truth["reference"],
        "direction": parsed.direction == truth["direction"],
        "amount": abs(parsed.amount - float(truth["amount"])) < 0.005,
        "balance": abs(parsed.balance - float(truth["balance"])) < 0.005,
    }


def evaluate(data_dir: str | Path, workers: int | None = None) -> dict:
    data_dir = Path(data_dir)
    truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))
    pdfs = sorted((data_dir / "statements").glob("*.pdf"))
    with ProcessPoolExecutor(workers) as pool:
        statements = list(pool.map(parse_statement, pdfs, chunksize=4))

    field_hits = defaultdict(int)
    rows_total = rows_exact = count_mismatches = 0
    by_client = defaultdict(list)
    for pdf, statement in zip(pdfs, statements):
        client, channel = pdf.stem.rsplit("_", 1)
        by_client[client].append(statement)
        expected = _truth_rows(data_dir / "transactions" / f"{pdf.stem}.csv")
        if len(expected) != len(statement.rows):
            count_mismatches += 1
        for parsed, row in zip(statement.rows, expected):
            hits = _field_matches(parsed, row, channel)
            for name, ok in hits.items():
                field_hits[name] += ok
            rows_total += 1
            rows_exact += all(hits.values())

    tp = fp = fn = 0
    pairs_found = pairs_true = pairs_right = 0
    tampered_transfers = tampered_disputed = 0
    for client, statements_ in by_client.items():
        report = verify_case(statements_)
        flagged = {b["row_id"] for s in report["statements"] for b in s["breaks"]}
        planted = {truth[client]["tamper"]["row_id"]} if truth[client]["tamper"] else set()
        tp += len(flagged & planted)
        fp += len(flagged - planted)
        fn += len(planted - flagged)
        # A transfer whose amount was tampered with should be disputed, not matched.
        found = {tuple(p) for p in report["transfers"]["matched"]}
        all_pairs = {tuple(p) for p in truth[client]["transfer_pairs"]}
        expected_pairs = {p for p in all_pairs if not planted & set(p)}
        disputed = {(m["wallet_row"], m["absa_row"]) for m in report["transfers"]["mismatched"]}
        pairs_found += len(found)
        pairs_true += len(expected_pairs)
        pairs_right += len(found & expected_pairs)
        tampered_transfers += len(all_pairs - expected_pairs)
        tampered_disputed += len((all_pairs - expected_pairs) & disputed)

    return {
        "statements": len(pdfs),
        "rows": rows_total,
        "row_count_mismatches": count_mismatches,
        "row_exact_match": rows_exact / rows_total,
        "field_accuracy": {f: field_hits[f] / rows_total for f in FIELDS},
        "tamper_detection": {
            "planted": tp + fn, "caught": tp, "false_alarms": fp,
            "precision": tp / (tp + fp) if tp + fp else 1.0,
            "recall": tp / (tp + fn) if tp + fn else 1.0,
        },
        "transfer_matching": {
            "true_pairs": pairs_true, "found": pairs_found, "correct": pairs_right,
            "precision": pairs_right / pairs_found if pairs_found else 1.0,
            "recall": pairs_right / pairs_true if pairs_true else 1.0,
            "tampered_transfers": tampered_transfers,
            "tampered_transfers_disputed": tampered_disputed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/synthetic")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.data), indent=2))


if __name__ == "__main__":
    main()
