import argparse
import json

from ..parsing import read_case
from . import label_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse, verify and label one client's statements.")
    parser.add_argument("pdfs", nargs="+", help="statement PDFs belonging to one client")
    parser.add_argument("--method", choices=("llm", "rules"), default="llm")
    parser.add_argument("--json", help="write the labelled ledger and reports here")
    args = parser.parse_args()

    statements, report = read_case(args.pdfs)
    summary = label_case(statements, args.method)
    print(f"{summary['rows']} rows labelled by {summary.get('model', 'keyword rules')}")
    if args.method == "llm":
        print(f"LLM calls {summary['llm_calls']}, cache hits {summary['cache_hits']}, "
              f"fell back to rules {len(summary['llm_fallbacks'])}")
    for category, n in summary["categories"].items():
        print(f"  {category:<22} {n}")
    rows = {r.row_id: r for s in statements for r in s.rows}
    for row_id in summary["injection_suspected"]:
        print(f"! {row_id}: description reads like an instruction, treated as data: "
              f"{rows[row_id].description!r} -> {rows[row_id].category}")
    others = [r for r in summary["needs_review"] if r not in summary["injection_suspected"]]
    if others:
        print(f"Needs review: {', '.join(others)}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"statements": [s.to_dict() for s in statements], "verification": report,
                       "labelling": summary}, f, indent=2)


if __name__ == "__main__":
    main()
