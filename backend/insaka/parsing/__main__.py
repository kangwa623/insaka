import argparse
import json
from collections import Counter

from . import read_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse and verify one client's statements.")
    parser.add_argument("pdfs", nargs="+", help="statement PDFs belonging to one client")
    parser.add_argument("--json", help="write the ledger and verification report here")
    args = parser.parse_args()

    statements, report = read_case(args.pdfs)
    for s, check in zip(statements, report["statements"]):
        trust = Counter(r.trust for r in s.rows)
        status = "reconciles" if check["reconciles"] else f"{len(check['breaks'])} break(s)"
        print(f"{s.statement_id}: {len(s.rows)} rows, {s.period}, {status}, "
              + ", ".join(f"{k} {v}" for k, v in trust.items()))
        for b in check["breaks"]:
            print(f"  ! {b['row_id']}: shows {b['shown_amount']:,.2f} "
                  f"but balances imply {b['implied_amount']:,.2f}")
    t = report["transfers"]
    print(f"Transfers: {len(t['matched'])} matched with Absa, {len(t['mismatched'])} disagree, "
          f"{len(t['unmatched'])} without a partner")
    print("PASSED" if report["passed"] else f"FLAGGED: {', '.join(report['flagged_rows'])}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"statements": [s.to_dict() for s in statements], "report": report}, f,
                      indent=2)


if __name__ == "__main__":
    main()
