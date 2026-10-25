"""Build feature tables for whole cohorts: the training cohort and the demo cohort.

Each client goes through what a real case goes through after parsing: verification
(trust levels, and the balance-implied amount for any row the tamper check caught),
labelling, then features. Rows come from the ground-truth CSVs, which the parser
reproduces exactly.

labels="truth" uses the generator's categories (training: Qwen matched them on every
held-out row, and labelling 2,000 clients would exceed the free tier); labels="llm"
uses Qwen's cached labels; labels="rules" uses the keyword baseline.
"""

import json
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from ..evaluation.labelling import load_case
from ..features import compute_features
from ..findings import detect_findings
from ..labelling import label_case
from ..parsing import verify_case
from .model import model_inputs


def prepare_case(data_dir: Path, client: dict, truth: dict, labels: str = "llm", labeller=None):
    """A client's statements as the pipeline would hold them: verified and labelled."""
    statements, row_truth = load_case(data_dir, client)
    for s in statements:
        s.opening_balance = truth["opening_balances"][s.channel]
        s.closing_balance = s.rows[-1].balance if s.rows else s.opening_balance
    report = verify_case(statements)
    if labels == "truth":
        for s in statements:
            for r in s.rows:
                r.category = row_truth[r.row_id]["category"]
                r.label_source = "truth"
    else:
        label_case(statements, labels, labeller)
    corrections = {b["row_id"]: b["implied_amount"]
                   for c in report["statements"] for b in c["breaks"]}
    return statements, report, corrections


def client_record(data_dir: Path, labels: str, item: tuple, labeller=None) -> dict:
    client, truth = item
    statements, report, corrections = prepare_case(data_dir, client, truth, labels, labeller)
    figures = compute_features(statements, client, corrections)
    findings = detect_findings(figures, client)
    features = {k: f.value for k, f in figures.items()}
    return {
        "client_id": client["client_id"],
        "gender": client["gender"],
        "province": client["province"],
        "features": features,
        "inputs": model_inputs(features, findings, client),
        "findings": sorted(findings),
        "verification_passed": report["passed"],
        "true_findings": truth["findings"],
        "true_features": truth["true_features"],
        "defaulted": truth["defaulted"],
    }


def build_table(data_dir: str | Path, labels: str = "llm", out: str | Path | None = None,
                workers: int | None = None) -> list[dict]:
    """One record per client; cached to out if given."""
    data_dir = Path(data_dir)
    if out and Path(out).exists():
        return json.loads(Path(out).read_text("utf-8"))
    clients = json.loads((data_dir / "clients.json").read_text("utf-8"))
    truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))
    items = [(c, truth[c["client_id"]]) for c in clients]
    with ProcessPoolExecutor(workers) as pool:
        records = list(pool.map(partial(client_record, data_dir, labels), items, chunksize=16))
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(records), "utf-8")
    return records
