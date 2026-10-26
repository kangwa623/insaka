import json

from insaka.agent import NoChat, run_case
from insaka.brief import build_brief
from insaka.case import load_ledger
from insaka.generator import MWILA_ID, generate


def test_mwila_brief_is_sourced_and_reads_the_season(tmp_path):
    generate(2, 42, tmp_path, pdfs=False)
    _, _, case = run_case(MWILA_ID, "rules", tmp_path, cases_dir=tmp_path / "cases",
                          agent_dir=tmp_path / "agent", label_method="rules",
                          memo_chat=NoChat(), registry={})
    client = next(c for c in json.loads((tmp_path / "clients.json").read_text("utf-8"))
                  if c["client_id"] == MWILA_ID)
    ledger = load_ledger(MWILA_ID, tmp_path / "cases")
    b = build_brief(case.data, ledger, client)
    ids = {r["row_id"] for r in ledger}

    t = b["trend"]
    assert t["verdict"] == "in line with what the season predicts"
    assert set(t["recent"]["rows"]) <= ids and t["recent"]["rows"]

    products = {p["product"] for p in b["products"]}
    assert products == {"merchant_collections", "seasonal_savings", "crop_asset_insurance",
                        "momo_repayments"}
    assert all(set(p["rows"]) <= ids for p in b["products"])
    assert "business_current_account" not in products   # already held

    assert b["open_issues"][-1]["kind"] == "next"
    for flag in b["risk_flags"] + b["context"]:
        assert all(f in case.data["figures"] for f in flag["figures"])
