"""Findings an RM should know about, detected by code from the features.

Each finding cites the figures (and so the rows) behind it. Seasonal income is context,
not a risk: a harvest spike that the season predicts is how the business trades.
Thresholds were tuned on the training cohort (seed 43), never on the demo cohort.
"""

import numpy as np

from .features import Figure, season_for
from .generator.seasons import HARVEST_MONTHS

THRESHOLDS = {
    "seasonal_peak_to_median": 1.8,     # the peak the season predicts, as the planted finding
    "season_fit": 0.5,                  # ...and the income really follows that season
    "drought_harvest_ratio": 0.6,       # harvest income vs what the season predicts
    "irregular_low_month_ratio": 0.37,  # weakest month vs a typical month, season allowed for
    "heavy_overdraft_share": 0.25,
    "dominant_customer_share": 0.5,
}

RISK_FINDINGS = ("drought_shock", "irregular_inflows", "heavy_overdraft", "dominant_customer")


def finding_stats(figures: dict[str, Figure], client: dict) -> dict[str, Figure]:
    """The extra figures the findings rest on, computed from the monthly income series."""
    season = season_for(client["archetype"])
    by_month = figures["monthly_income"].detail["by_month"]
    months = list(by_month)
    deseasoned = {k: by_month[k]["value"] / season[int(k[5:])] for k in months}
    level = float(np.median(list(deseasoned.values())))
    weakest = min(months, key=lambda k: deseasoned[k])
    harvest = [k for k in months if int(k[5:]) in HARVEST_MONTHS]
    off_season = [k for k in months if int(k[5:]) not in HARVEST_MONTHS]
    has_harvest = max(season[int(k[5:])] for k in months) >= 1.8 and harvest and off_season
    if has_harvest:
        expected = sum(season[int(k[5:])] for k in harvest) * float(
            np.median([deseasoned[k] for k in off_season]))
        actual = sum(by_month[k]["value"] for k in harvest)
        harvest_ratio = actual / expected if expected else 1.0
        harvest_rows = [r for k in harvest for r in by_month[k]["rows"]]
    else:
        harvest_ratio, harvest_rows = 1.0, []
    expected = np.array([season[int(k[5:])] for k in months])
    observed = np.array([by_month[k]["value"] for k in months])
    follows = (float(np.corrcoef(expected, observed)[0, 1])
               if expected.std() > 0 and observed.std() > 0 else 0.0)
    stats = [
        Figure("season_peak_ratio", "Peak the business's season predicts, against a typical month",
               float(expected.max() / np.median(expected)), "x", [],
               {"months": months, "source": "season calendar"}),
        Figure("season_fit", "How closely income follows the expected season", follows, "",
               figures["monthly_income"].rows),
        Figure("weakest_month", "The weakest month, allowing for the season", weakest, "month",
               by_month[weakest]["rows"]),
        Figure("weakest_month_ratio", "Weakest month against a typical month, allowing for "
               "the season", deseasoned[weakest] / level if level else 0.0, "%",
               by_month[weakest]["rows"], {"month": weakest}),
        Figure("harvest_ratio", "Harvest-season income against what the season predicts",
               harvest_ratio, "%", harvest_rows, {"months": harvest if has_harvest else []}),
    ]
    return {f.name: f for f in stats}


def detect_findings(figures: dict[str, Figure], client: dict) -> dict[str, dict]:
    """finding -> {"risk": bool, "evidence": [figure names]}; figures gains the stats used."""
    figures.update(finding_stats(figures, client))
    t, v = THRESHOLDS, {k: f.value for k, f in figures.items()}
    found = {}
    drought = v["harvest_ratio"] < t["drought_harvest_ratio"]
    if drought:
        found["drought_shock"] = ["harvest_ratio", "monthly_income"]
    elif (v["season_peak_ratio"] >= t["seasonal_peak_to_median"]
          and v["season_fit"] >= t["season_fit"]):
        found["seasonal_income"] = ["peak_month_income", "peak_to_median", "season_fit",
                                    "deseasoned_income_cv"]
    if v["weakest_month_ratio"] < t["irregular_low_month_ratio"] and not drought:
        found["irregular_inflows"] = ["weakest_month_ratio", "monthly_income"]
    if v["overdraft_day_share"] >= t["heavy_overdraft_share"]:
        found["heavy_overdraft"] = ["overdraft_day_share"]
    if v["top_customer_share"] > t["dominant_customer_share"]:
        found["dominant_customer"] = ["top_customer_share"]
    return {k: {"risk": k in RISK_FINDINGS, "evidence": e} for k, e in found.items()}
