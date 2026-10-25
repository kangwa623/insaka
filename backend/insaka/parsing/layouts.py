"""Statement layouts the parser knows. A new statement format is a new entry here."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Layout:
    channel: str
    title: str                  # first line of page 1, used to recognise the layout
    columns: tuple[str, ...]    # table header labels, left to right
    numeric: tuple[str, ...]    # right-aligned money columns
    date: str                   # column holding the date, which starts every row
    date_format: str
    description: str            # the only column that wraps onto extra lines
    reference: str
    signed_amount: str = ""     # single +/- amount column, if the layout uses one


LAYOUTS = (
    Layout("absa", "Business Current Account Statement",
           ("Date", "Description", "Reference", "Debit", "Credit", "Balance"),
           ("Debit", "Credit", "Balance"), "Date", "%d/%m/%Y", "Description", "Reference"),
    Layout("mtn", "Mobile Money Transaction Statement",
           ("Date & Time", "Transaction ID", "Details", "Amount (ZMW)", "Balance"),
           ("Amount (ZMW)", "Balance"), "Date & Time", "%Y-%m-%d %H:%M:%S", "Details",
           "Transaction ID", signed_amount="Amount (ZMW)"),
    Layout("airtel", "Airtel Money Account Statement",
           ("Date", "Transaction ID", "Type", "Description", "Debit", "Credit", "Balance"),
           ("Debit", "Credit", "Balance"), "Date", "%d-%b-%Y", "Description", "Transaction ID"),
)


def detect_layout(first_line: str) -> Layout:
    for layout in LAYOUTS:
        if first_line.strip().startswith(layout.title):
            return layout
    raise ValueError(f"Unrecognised statement layout: {first_line!r}")
