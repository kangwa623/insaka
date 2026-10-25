"""Read statements into the standard ledger and check they haven't been edited.

    python -m insaka.parsing data/synthetic/statements/MWILA-001_absa.pdf data/synthetic/statements/MWILA-001_mtn.pdf
"""

from pathlib import Path

from ..ledger import Statement
from .pdf import ParseError, parse_statement
from .verify import cross_match, reconcile, verify_case

__all__ = ["ParseError", "parse_statement", "reconcile", "cross_match", "verify_case",
           "read_case"]


def read_case(paths: list[str | Path]) -> tuple[list[Statement], dict]:
    """Parse one client's statements and verify them together."""
    statements = [parse_statement(p) for p in paths]
    return statements, verify_case(statements)
