"""Pre-label every client with the language model, so the app and evaluations read the cache.

    python -m insaka.labelling.batch --data data/synthetic

Clients already cached cost nothing. The free tier allows 200,000 tokens a day, about
35 clients; when that runs out it stops and says how far it got, or with --wait it waits
for the quota and carries on.
"""

import argparse
import json
import re
import time
from pathlib import Path

from ..evaluation.labelling import load_case
from . import label_case
from .llm import LLMLabeller


def _quota_wait(error: Exception) -> float | None:
    """Seconds Groq asks us to wait after a rate limit ("try again in 14m44.3s"), if any."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", str(error))
    if "RateLimit" not in type(error).__name__ or not m:
        return None
    h, mins, s = m.groups()
    return int(h or 0) * 3600 + int(mins or 0) * 60 + float(s) + 30


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/synthetic")
    parser.add_argument("--wait", action="store_true",
                        help="when the daily quota runs out, wait for it and carry on")
    args = parser.parse_args()
    data_dir = Path(args.data)
    clients = json.loads((data_dir / "clients.json").read_text("utf-8"))
    labeller = LLMLabeller()
    for i, client in enumerate(clients, start=1):
        while True:
            statements, _ = load_case(data_dir, client)
            calls = labeller.calls
            try:
                summary = label_case(statements, "llm", labeller)
                break
            except Exception as e:
                wait = _quota_wait(e) if args.wait else None
                if wait is None:
                    print(f"Stopped at {client['client_id']} ({i - 1} of {len(clients)} done): "
                          f"{type(e).__name__}: {e}")
                    raise SystemExit(1)
                print(f"Daily quota used up at {client['client_id']}; waiting {wait / 60:.0f} min",
                      flush=True)
                time.sleep(wait)
        print(f"{i}/{len(clients)} {client['client_id']}: {summary['rows']} rows, "
              f"{labeller.calls - calls} calls, {len(summary['llm_fallbacks'])} fell back",
              flush=True)
    print(f"Done: {labeller.calls} calls, {labeller.cache_hits} cache hits")


if __name__ == "__main__":
    main()
