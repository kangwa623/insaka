import argparse
import time

from . import generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic Insaka statements.")
    parser.add_argument("--n", type=int, default=150, help="number of clients besides Mwila")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="data/synthetic")
    parser.add_argument("--no-pdf", action="store_true", help="skip rendering statement PDFs")
    args = parser.parse_args()

    start = time.perf_counter()
    summary = generate(args.n, args.seed, args.out, pdfs=not args.no_pdf)
    print(f"{summary['clients']} clients, default rate {summary['default_rate']:.1%}, "
          f"written to {args.out} in {time.perf_counter() - start:.1f}s")


# The guard matters: PDF workers re-import this module on Windows.
if __name__ == "__main__":
    main()
