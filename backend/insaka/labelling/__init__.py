"""Give every ledger row a category, with the words it rests on.

    python -m insaka.labelling data/synthetic/statements/MWILA-001_absa.pdf data/synthetic/statements/MWILA-001_mtn.pdf

method="llm" uses Qwen (the cache first); method="rules" uses the keyword baseline only.
"""

from collections import Counter

from ..ledger import Statement
from .injection import looks_like_injection
from .masking import mask_case
from .payees import summarise_payees
from .rules import rule_label

__all__ = ["label_case", "client_of"]


def client_of(statements: list[Statement]) -> str:
    """MWILA-001-ABSA -> MWILA-001"""
    return statements[0].statement_id.rsplit("-", 1)[0]


def label_case(statements: list[Statement], method: str = "llm", labeller=None) -> dict:
    """Label one client's rows in place and summarise what happened."""
    rows = [row for s in statements for row in s.rows]
    llm_labels = {}
    if method == "llm":
        from .llm import LLMLabeller

        labeller = labeller or LLMLabeller()
        masked, _ = mask_case(statements)
        payees = summarise_payees(statements, masked)
        llm_labels = labeller.label(client_of(statements), rows, masked, payees)
    elif method != "rules":
        raise ValueError(f"unknown method {method!r}")

    fallbacks = []
    for row in rows:
        if row.row_id in llm_labels:
            row.category, row.label_quote = llm_labels[row.row_id]
            row.label_source = f"llm:{labeller.model}"
            row.needs_review = False
        else:
            row.category, rule_id, row.label_quote = rule_label(row)
            row.label_source = f"rules:{rule_id}"
            row.needs_review = rule_id == "fallback.none"
            if method == "llm":
                fallbacks.append(row.row_id)
                row.needs_review = True
    injection = [row.row_id for row in rows if looks_like_injection(row.description)]
    for row in rows:
        if row.row_id in injection:
            row.needs_review = True

    summary = {
        "method": method,
        "rows": len(rows),
        "categories": dict(Counter(row.category for row in rows).most_common()),
        "needs_review": [row.row_id for row in rows if row.needs_review],
        "injection_suspected": injection,
        "llm_fallbacks": fallbacks,
    }
    if method == "llm":
        summary.update(model=labeller.model, llm_calls=labeller.calls,
                       cache_hits=labeller.cache_hits)
    return summary
