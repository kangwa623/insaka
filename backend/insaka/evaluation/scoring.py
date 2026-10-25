"""Does the risk score work, and do statements add anything? Measured against outcomes.

    python -m insaka.evaluation.scoring

- Train on half of the seed-43 training cohort (1,000 clients); test on the other half
  and on the 151-client demo cohort.
- Logistic regression (application + statements) against: application only (the
  ablation), gradient boosting (the challenger), and approve-everyone.
- AUROC and Brier with 95% bootstrap intervals; calibration by fifths of predicted risk.
- Finding detection against the planted findings; fairness by gender and province.
- On demo clients Qwen has already labelled, features from Qwen's labels are compared
  with features from the generator's categories, to show the substitution changes nothing.

Writes data/evaluation/scoring.json and saves the model to models/risk_lr.joblib.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from ..findings import THRESHOLDS
from ..generator.findings import FINDINGS
from ..labelling.llm import DEFAULT_MODEL, LLMLabeller
from ..scoring import model as risk
from ..scoring.cohort import build_table, client_record

N_TRAIN = 1000


def _auroc(y, p):
    return float(roc_auc_score(y, p)) if 0 < sum(y) < len(y) else float("nan")


def bootstrap(y, preds: dict, n_boot: int = 1000, seed: int = 0) -> dict:
    """AUROC/Brier with 95% CIs per model, and the paired AUROC gain of full over app-only."""
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    stats = defaultdict(list)
    for _ in range(n_boot):
        i = rng.integers(len(y), size=len(y))
        if y[i].min() == y[i].max():
            continue
        for name, p in preds.items():
            p = np.asarray(p)
            stats[f"{name}.auroc"].append(roc_auc_score(y[i], p[i]))
            stats[f"{name}.brier"].append(brier_score_loss(y[i], p[i]))
        if "logistic" in preds and "application_only" in preds:
            stats["gain.auroc"].append(stats["logistic.auroc"][-1]
                                       - stats["application_only.auroc"][-1])
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
            for k, v in stats.items()}


def calibration(y, p, bins: int = 5) -> list[dict]:
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        out.append({"mean_predicted": float(np.mean(np.asarray(p)[chunk])),
                    "observed_default_rate": float(np.mean(np.asarray(y)[chunk])),
                    "clients": int(len(chunk))})
    return out


def test_set(name: str, records: list[dict], models: dict, base_rate: float) -> dict:
    y = [int(r["defaulted"]) for r in records]
    inputs = [r["inputs"] for r in records]
    preds = {
        "logistic": models["logistic"].predict_proba(risk.matrix(inputs, risk.APPLICATION + risk.STATEMENT))[:, 1],
        "application_only": models["application_only"].predict_proba(risk.matrix(inputs, risk.APPLICATION))[:, 1],
        "gradient_boosting": models["gradient_boosting"].predict_proba(risk.matrix(inputs, risk.APPLICATION + risk.STATEMENT))[:, 1],
        "approve_everyone": np.full(len(y), base_rate),
    }
    ci = bootstrap(y, {k: v for k, v in preds.items() if k != "approve_everyone"})
    result = {"clients": len(y), "defaults": int(sum(y)), "models": {}}
    for k, p in preds.items():
        result["models"][k] = {"auroc": _auroc(y, p), "brier": float(brier_score_loss(y, p)),
                               "auroc_ci95": ci.get(f"{k}.auroc"), "brier_ci95": ci.get(f"{k}.brier")}
    result["models"]["approve_everyone"]["auroc"] = 0.5
    result["statement_gain_auroc"] = {
        "value": result["models"]["logistic"]["auroc"] - result["models"]["application_only"]["auroc"],
        "ci95": ci.get("gain.auroc")}
    result["calibration_logistic"] = calibration(y, preds["logistic"])
    fairness = {}
    for field in ("gender", "province"):
        groups = defaultdict(list)
        for r, p in zip(records, preds["logistic"]):
            groups[r[field]].append((int(r["defaulted"]), float(p)))
        fairness[field] = {g: {"clients": len(v), "defaults": sum(a for a, _ in v),
                               "auroc": _auroc([a for a, _ in v], [b for _, b in v]),
                               "mean_pd": float(np.mean([b for _, b in v])),
                               "default_rate": float(np.mean([a for a, _ in v]))}
                           for g, v in sorted(groups.items())}
    result["fairness"] = fairness
    return result


def finding_scores(records: list[dict]) -> dict:
    out = {}
    for f in FINDINGS:
        tp = sum(f in r["findings"] and f in r["true_findings"] for r in records)
        fp = sum(f in r["findings"] and f not in r["true_findings"] for r in records)
        fn = sum(f not in r["findings"] and f in r["true_findings"] for r in records)
        p = tp / (tp + fp) if tp + fp else 1.0
        rc = tp / (tp + fn) if tp + fn else 1.0
        out[f] = {"precision": p, "recall": rc, "f1": 2 * p * rc / (p + rc) if p + rc else 0.0,
                  "planted": tp + fn}
    return out


class _CacheOnly:
    """A chat that refuses to call the API: only clients Qwen already labelled are used."""

    model = DEFAULT_MODEL

    def __call__(self, system, user):
        raise LookupError("not cached")


def qwen_consistency(data_dir: Path, demo: list[dict]) -> dict:
    clients = {c["client_id"]: c for c in json.loads((data_dir / "clients.json").read_text("utf-8"))}
    truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))
    by_id = {r["client_id"]: r for r in demo}
    labeller = LLMLabeller(_CacheOnly())
    bundle = risk.load()
    compared, max_diff, finding_mismatch, max_pd_diff = [], {}, 0, 0.0
    for cid in clients:
        try:
            rec = client_record(data_dir, "llm", (clients[cid], truth[cid]), labeller)
        except LookupError:
            continue
        base = by_id[cid]
        compared.append(cid)
        for k, v in rec["features"].items():
            if isinstance(v, str):   # e.g. the peak month
                max_diff[k] = max(max_diff.get(k, 0.0), float(v != base["features"][k]))
                continue
            diff = abs(v - base["features"][k])
            max_diff[k] = max(max_diff.get(k, 0.0), diff)
        finding_mismatch += rec["findings"] != base["findings"]
        pds = [risk.score(bundle, r["inputs"])["pd"] for r in (rec, base)]
        max_pd_diff = max(max_pd_diff, abs(pds[0] - pds[1]))
    return {"clients": len(compared), "max_pd_difference": round(max_pd_diff, 4),
            "max_feature_difference": {k: round(v, 6) for k, v in max_diff.items()},
            "clients_with_different_findings": finding_mismatch}


def evaluate(train_dir="data/training", demo_dir="data/synthetic") -> dict:
    train_dir, demo_dir = Path(train_dir), Path(demo_dir)
    cohort = build_table(train_dir, "truth", train_dir / "features_truth.json")
    demo = build_table(demo_dir, "truth", demo_dir / "features_truth.json")
    train, holdout = cohort[:N_TRAIN], cohort[N_TRAIN:]
    y = [int(r["defaulted"]) for r in train]
    inputs = [r["inputs"] for r in train]
    full = risk.APPLICATION + risk.STATEMENT
    models = {
        "logistic": risk.logistic().fit(risk.matrix(inputs, full), y),
        "application_only": risk.logistic().fit(risk.matrix(inputs, risk.APPLICATION), y),
        "gradient_boosting": risk.challenger().fit(risk.matrix(inputs, full), y),
    }
    risk.save({"model": models["logistic"], "columns": full, "trained_on": len(train),
               "base_rate": float(np.mean(y))})
    base_rate = float(np.mean(y))
    return {
        "train": {"clients": len(train), "defaults": int(sum(y)), "cohort_seed": 43},
        "holdout": test_set("holdout", holdout, models, base_rate),
        "demo": test_set("demo", demo, models, base_rate),
        "findings": {"demo": finding_scores(demo), "holdout": finding_scores(holdout),
                     "thresholds": THRESHOLDS},
        "qwen_consistency": qwen_consistency(demo_dir, demo),
        "coefficients": dict(zip(full, models["logistic"][-1].coef_[0].round(3).tolist())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/evaluation/scoring.json")
    args = parser.parse_args()
    r = evaluate()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(r, indent=2), "utf-8")
    for name in ("holdout", "demo"):
        t = r[name]
        print(f"{name}: {t['clients']} clients, {t['defaults']} defaults")
        for m, s in t["models"].items():
            ci = s["auroc_ci95"] and np.round(s["auroc_ci95"], 3).tolist()
            print(f"  {m:<18} AUROC {s['auroc']:.3f} {ci or ''}  Brier {s['brier']:.4f}")
        g = t["statement_gain_auroc"]
        print(f"  statements add AUROC {g['value']:+.3f} {np.round(g['ci95'], 3).tolist()}")
        print("  calibration (predicted vs observed): " + ", ".join(
            f"{c['mean_predicted']:.2f}/{c['observed_default_rate']:.2f}"
            for c in t["calibration_logistic"]))
        print("  by gender: " + ", ".join(f"{g} AUROC {v['auroc']:.3f}"
                                         for g, v in t["fairness"]["gender"].items()))
    for name in ("demo", "holdout"):
        print(f"findings ({name}): " + ", ".join(f"{f} F1 {s['f1']:.2f}"
                                                for f, s in r["findings"][name].items()))
    print(f"Qwen consistency: {r['qwen_consistency']}")
    print(f"Written to {args.out}; model saved to {risk.MODEL_PATH}")


if __name__ == "__main__":
    main()
