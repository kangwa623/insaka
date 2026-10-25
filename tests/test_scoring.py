import json

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from insaka.generator import generate
from insaka.scoring import model as risk
from insaka.scoring.cohort import build_table


@pytest.fixture(scope="session")
def tables(tmp_path_factory):
    out = tmp_path_factory.mktemp("scoring")
    generate(600, 11, out, pdfs=False)
    records = build_table(out, "truth")
    return records[:400], records[400:]


def test_statements_beat_application_only_and_approve_everyone(tables):
    train, test = tables
    y = [r["defaulted"] for r in train]
    yt = [r["defaulted"] for r in test]
    full = risk.APPLICATION + risk.STATEMENT
    lr = risk.logistic().fit(risk.matrix([r["inputs"] for r in train], full), y)
    app = risk.logistic().fit(risk.matrix([r["inputs"] for r in train], risk.APPLICATION), y)
    auc_full = roc_auc_score(yt, lr.predict_proba(risk.matrix([r["inputs"] for r in test], full))[:, 1])
    auc_app = roc_auc_score(yt, app.predict_proba(
        risk.matrix([r["inputs"] for r in test], risk.APPLICATION))[:, 1])
    assert auc_full > auc_app + 0.05 and auc_full > 0.7


def test_score_gives_pd_band_and_reasons(tables):
    train, _ = tables
    bundle = risk.train([r["inputs"] for r in train], [r["defaulted"] for r in train])
    worst = max(train, key=lambda r: r["inputs"]["overdraft_day_share"])
    s = risk.score(bundle, worst["inputs"])
    assert 0 < s["pd"] < 1 and s["band"] in {"Low", "Medium", "High"}
    assert any(r["input"] == "overdraft_day_share" for r in s["raises_risk"])
    assert all(r["text"] for r in s["raises_risk"] + s["lowers_risk"])


def test_saved_model_scores_mwila_low():
    bundle = risk.load()
    mwila = next(c for c in json.loads(open("data/synthetic/clients.json", encoding="utf-8").read())
                 if c["client_id"] == "MWILA-001")
    truth = json.loads(open("data/synthetic/ground_truth.json", encoding="utf-8").read())["MWILA-001"]
    inputs = risk.model_inputs(truth["true_features"] | {"mobile_money_share": 0.55},
                               truth["findings"], mwila)
    assert risk.score(bundle, inputs)["band"] == "Low"
