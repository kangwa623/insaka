"""Spot statement text that tries to give instructions instead of describing a payment.

A flagged row is still labelled like any other: the text is data, never an instruction.
The flag only puts it in front of the RM.
"""

import re

PATTERNS = [
    r"\bignore\b.*\binstructions?\b",
    r"\bdisregard\b",
    r"\bapprov(e|al|ed)\b",
    r"\brisk score\b",
    r"^\s*(system|assistant|user)\s*[:,]",
    r"\b(you are|act as)\b",
]

_INJECTION = re.compile("|".join(PATTERNS), re.IGNORECASE)


def looks_like_injection(description: str) -> bool:
    return bool(_INJECTION.search(description))
