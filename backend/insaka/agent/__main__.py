import argparse
import json

from . import run_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Insaka agent on one client's case.")
    parser.add_argument("client_id")
    parser.add_argument("--mode", choices=("llm", "rules"), default="llm")
    parser.add_argument("--data", default="data/synthetic")
    parser.add_argument("--absa-months", type=int, help="keep only the last N months of Absa "
                        "history (to exercise the six-month rule)")
    args = parser.parse_args()

    label = f"absa{args.absa_months}" if args.absa_months else ""
    run, _, case = run_case(args.client_id, args.mode, args.data, label=label,
                            absa_months=args.absa_months)
    print(f"Agent ({run['model']}{', replayed from cache' if run['replayed'] else ''}) "
          f"on {run['client_id']}: {run['steps_used']} steps, {run['refused_calls']} refused, "
          f"{run['tokens']:,} tokens")
    for s in run["steps"]:
        mark = {"ok": " ", "refused": "x", "error": "!", "no_tool_call": "?",
                "model_unavailable": "~"}[s["status"]]
        args_text = json.dumps(s["args"]) if s["args"] else ""
        print(f" {mark} {s['step']:>2}. {s['tool'] or '(no tool)'} {args_text}")
        if s["reason"]:
            print(f"       why: {s['reason']}")
        if s["status"] != "ok":
            print(f"       {s['status']}: {s['result']}")
    if run["model_fallback"]:
        print(f"Model unavailable ({run['model_fallback'][:80]}...); the rules agent finished "
              "the case. Not cached: the next run tries the model again.")
    for e in run["escalations"]:
        print(f"Escalated ({e['kind']}{', stopped' if e['stop'] else ''}): {e['reason']}")
    if run["memo"]:
        m = run["memo"]
        print(f"Memo by {m['written_by']}: {m['figures_used']} figures, {m['figures_linked']} "
              f"linked, {m['unsupported_numbers']} without a source")
    print(f"Case status: {case.status}")


if __name__ == "__main__":
    main()
