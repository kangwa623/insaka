"""Synthetic SME and farmer statements with known ground truth.

    python -m insaka.generator --n 150 --seed 42 --out data/synthetic
"""

import csv
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .findings import inject, tamper
from .outcomes import assign_outcomes, risk_logit, true_features
from .profiles import make_profile, mwila_profile
from .render_pdf import render_statement
from .seasons import STATEMENT_END
from .transactions import build_ledgers

MWILA_ID = "MWILA-001"
TAMPER_RATE = 0.05
N_INJECTED = 3

CSV_FIELDS = ["row_id", "date", "time", "description", "reference", "direction", "amount",
              "balance", "true_category", "true_amount", "counterparty", "tampered",
              "injection", "pair_ref"]


def generate(n: int = 150, seed: int = 42, out: str | Path = "data/synthetic",
             pdfs: bool = True) -> dict:
    out = Path(out)
    entries = [mwila_profile()]
    entries += [make_profile(i, np.random.default_rng([seed, i])) for i in range(1, n + 1)]

    for i, entry in enumerate(entries):
        rng = entry.pop("rng", None) or np.random.default_rng([seed, i, 1])
        entry["result"] = build_ledgers(entry, rng)

    _plant_adversarial(entries, np.random.default_rng([seed, 999]))

    for entry in entries:
        entry["features"] = true_features(entry, entry["result"])
        entry["logit"] = risk_logit(entry, entry["features"])
    assign_outcomes(entries, np.random.default_rng([seed, 1000]))
    entries[0]["defaulted"] = False  # Mwila's story: she repays

    _write(entries, out, seed, pdfs)
    return {"clients": len(entries),
            "default_rate": float(np.mean([e["defaulted"] for e in entries]))}


def _plant_adversarial(entries: list[dict], rng: np.random.Generator) -> None:
    others = list(range(1, len(entries)))
    n_tamper = max(1, round(TAMPER_RATE * len(others)))
    chosen = rng.choice(others, size=min(len(others), n_tamper + N_INJECTED), replace=False)
    for k, idx in enumerate(chosen):
        entry = entries[idx]
        ledgers = entry["result"]["ledgers"]
        usable = [c for c, rows in ledgers.items()
                  if sum(r["direction"] == "credit" for r in rows) >= 5]
        channel = str(rng.choice(usable))
        if k < n_tamper:
            entry["result"]["tamper"] = {"channel": channel, **tamper(ledgers[channel], rng)}
        else:
            entry["result"]["injection_rows"] = inject(ledgers[channel], rng)


def _write(entries: list[dict], out: Path, seed: int, pdfs: bool) -> None:
    (out / "transactions").mkdir(parents=True, exist_ok=True)
    if pdfs:
        (out / "statements").mkdir(parents=True, exist_ok=True)

    clients, truth, jobs = [], {}, []
    for entry in entries:
        p, h, res = entry["profile"], entry["hidden"], entry["result"]
        cid = p["client_id"]
        clients.append(p)
        truth[cid] = {
            "findings": h["findings"],
            "tamper": res.get("tamper"),
            "injection_rows": res.get("injection_rows", []),
            "transfer_pairs": res["transfer_pairs"],
            "dominant_customer": res["dominant_customer"],
            "monthly_takings": res["monthly_takings"],
            "opening_balances": res["opening"],
            "true_features": entry["features"],
            "pd": entry["pd"],
            "defaulted": entry["defaulted"],
        }
        for channel, rows in res["ledgers"].items():
            with open(out / "transactions" / f"{cid}_{channel}.csv", "w", newline="",
                      encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for r in rows:
                    writer.writerow({**r, "date": f"{r['ts']:%Y-%m-%d}",
                                     "time": f"{r['ts']:%H:%M:%S}", "pair_ref": r["pair_ref"] or ""})
            if pdfs:
                jobs.append((out / "statements" / f"{cid}_{channel}.pdf", channel, p, rows,
                             res["opening"][channel]))

    # PDF rendering dominates the run time, so spread it across cores.
    if jobs:
        with ProcessPoolExecutor() as pool:
            list(pool.map(_render, jobs, chunksize=8))

    manifest = {"seed": seed, "clients": len(entries), "statement_end": str(STATEMENT_END),
                "default_rate": round(float(np.mean([e["defaulted"] for e in entries])), 4),
                "synthetic": True}
    _dump(out / "clients.json", clients)
    _dump(out / "ground_truth.json", truth)
    _dump(out / "manifest.json", manifest)


def _render(job: tuple) -> None:
    render_statement(*job)


def _dump(path: Path, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
