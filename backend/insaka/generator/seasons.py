"""Zambian seasonal patterns and the statement window."""

from datetime import date

# Every statement ends here; histories run 6-12 months back from it.
STATEMENT_END = date(2026, 9, 30)

# School terms start in January, May and September.
SCHOOL_TERM_MONTHS = (1, 5, 9)

# ZRA turnover tax is paid quarterly.
TAX_MONTHS = (1, 4, 7, 10)

HARVEST_MONTHS = (5, 6, 7)

# Monthly income multipliers by pattern, before noise. Each averages to about 1.
SEASONAL = {
    # Maize and crop sales: lean Jan-Mar, harvest spike from May.
    "harvest": {1: 0.40, 2: 0.35, 3: 0.45, 4: 0.75, 5: 2.60, 6: 2.00, 7: 1.40,
                8: 0.95, 9: 0.80, 10: 0.70, 11: 0.85, 12: 0.75},
    # Seed and fertiliser sales peak before planting (Oct-Dec).
    "inputs": {1: 0.80, 2: 0.55, 3: 0.50, 4: 0.55, 5: 0.75, 6: 0.80, 7: 0.85,
               8: 1.00, 9: 1.40, 10: 1.80, 11: 1.95, 12: 1.05},
    # Mwila trades both: harvest spike in May, input sales before planting.
    "maize_and_inputs": {1: 0.60, 2: 0.50, 3: 0.60, 4: 0.90, 5: 2.40, 6: 1.60,
                         7: 1.10, 8: 0.90, 9: 1.00, 10: 1.30, 11: 1.35, 12: 0.85},
    # Shops: December peak, January dip.
    "retail": {1: 0.75, 2: 0.85, 3: 0.95, 4: 1.00, 5: 0.95, 6: 0.95, 7: 1.00,
               8: 1.00, 9: 1.00, 10: 1.00, 11: 1.10, 12: 1.45},
    # Construction runs in the dry season.
    "dry_season": {1: 0.70, 2: 0.70, 3: 0.80, 4: 0.95, 5: 1.10, 6: 1.20, 7: 1.20,
                   8: 1.20, 9: 1.15, 10: 1.10, 11: 0.95, 12: 0.85},
    # Tailors: school uniforms in January, festive wear in December.
    "uniforms": {1: 1.60, 2: 0.80, 3: 0.75, 4: 0.85, 5: 1.10, 6: 0.80, 7: 0.80,
                 8: 0.85, 9: 1.05, 10: 0.85, 11: 0.95, 12: 1.30},
    "flat": {m: 1.0 for m in range(1, 13)},
}


def statement_months(n_months: int) -> list[tuple[int, int]]:
    """The last n_months calendar months up to STATEMENT_END, oldest first."""
    year, month = STATEMENT_END.year, STATEMENT_END.month
    months = []
    for _ in range(n_months):
        months.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return months[::-1]


def days_in_month(year: int, month: int) -> int:
    next_month = date(year + month // 12, month % 12 + 1, 1)
    return (next_month - date(year, month, 1)).days
