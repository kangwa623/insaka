"""The risk score: logistic regression with readable reasons, gradient boosting as challenger.

Inputs are what the RM has (the application) plus what the statements show. Seasonality
is not an input: volatility is measured after allowing for the season, so a harvest
spike the calendar predicts costs the borrower nothing.
"""

from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_PATH = Path("models/risk_lr.joblib")

# TPIN registration, loan size and mobile-money share are left out: trained on the
# cohort, their weights came out against credit sense (being tax-registered or paid by
# MoMo raising risk) and dropping them cost no accuracy. A model the RM must explain
# can't carry reasons like those. TPIN is still checked with ZRA by the agent.
APPLICATION = ("years_trading", "pacra_registered", "bureau_adverse", "bureau_no_hit")
STATEMENT = ("deseasoned_income_cv", "overdraft_day_share", "top_customer_share",
             "log_debt_service_coverage", "drought_shock")

# Plain language for each input, and the figure it rests on (None: from the application).
REASONS = {
    "years_trading": ("years in business", None),
    "pacra_registered": ("PACRA registration", None),
    "tpin_registered": ("ZRA TPIN registration", None),
    "bureau_adverse": ("an adverse credit-bureau record", None),
    "bureau_no_hit": ("no credit-bureau history (thin file)", None),
    "log_requested_amount": ("the size of the loan requested", None),
    "deseasoned_income_cv": ("how much income varies beyond the normal season",
                             "deseasoned_income_cv"),
    "overdraft_day_share": ("days spent in overdraft", "overdraft_day_share"),
    "top_customer_share": ("reliance on the largest customer", "top_customer_share"),
    "log_debt_service_coverage": ("surplus cover for the new instalment",
                                  "debt_service_coverage"),
    "drought_shock": ("a harvest well below what the season predicts", "harvest_ratio"),
    "mobile_money_share": ("share of income arriving by mobile money", "mobile_money_share"),
}

BANDS = ((0.05, "Low"), (0.15, "Medium"), (1.01, "High"))

# Smaller pushes on the log-odds aren't worth an RM's attention as a reason.
MIN_EFFECT = 0.1


def model_inputs(features: dict, findings, client: dict) -> dict:
    """The model's inputs for one client; features are plain values (name -> number)."""
    app = client["application"]
    return {
        "years_trading": client["years_trading"],
        "pacra_registered": float(app["pacra_registered"]),
        "tpin_registered": float(app["tpin_registered"]),
        "bureau_adverse": float(app["bureau_status"] == "adverse"),
        "bureau_no_hit": float(app["bureau_status"] == "no_hit"),
        "log_requested_amount": float(np.log(app["requested_amount"])),
        "deseasoned_income_cv": features["deseasoned_income_cv"],
        "overdraft_day_share": features["overdraft_day_share"],
        "top_customer_share": features["top_customer_share"],
        "log_debt_service_coverage": float(np.log(np.clip(features["debt_service_coverage"],
                                                          0.1, 20))),
        "drought_shock": float("drought_shock" in findings),
        "mobile_money_share": features["mobile_money_share"],
    }


def matrix(inputs: list[dict], columns) -> np.ndarray:
    return np.array([[x[c] for c in columns] for x in inputs], dtype=float)


def logistic(columns=APPLICATION + STATEMENT):
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))


def challenger():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300,
                                          random_state=0)


def train(inputs: list[dict], y) -> dict:
    columns = APPLICATION + STATEMENT
    model = logistic().fit(matrix(inputs, columns), y)
    return {"model": model, "columns": columns}


def save(bundle: dict, path: Path = MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load(path: Path = MODEL_PATH) -> dict:
    return joblib.load(path)


def band(pd: float) -> str:
    return next(name for limit, name in BANDS if pd < limit)


def score(bundle: dict, inputs: dict, top: int = 3) -> dict:
    """PD, band, and the inputs that push risk up or down most, in plain language."""
    columns, model = bundle["columns"], bundle["model"]
    x = matrix([inputs], columns)
    pd = float(model.predict_proba(x)[0, 1])
    scaler, lr = model[0], model[-1]
    contributions = (scaler.transform(x)[0]) * lr.coef_[0]
    order = np.argsort(contributions)
    reasons = [{"input": columns[i], "text": REASONS[columns[i]][0],
                "figure": REASONS[columns[i]][1], "effect": round(float(contributions[i]), 3)}
               for i in order]
    return {
        "pd": pd,
        "band": band(pd),
        "raises_risk": [r for r in reversed(reasons) if r["effect"] >= MIN_EFFECT][:top],
        "lowers_risk": [r for r in reasons if r["effect"] <= -MIN_EFFECT][:top],
    }
