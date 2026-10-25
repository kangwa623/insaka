"""Rules-based statement parser. No AI is involved, so nothing can be invented here.

Columns are located from the table header on each page. Left-aligned text columns
claim words by their left edge; money columns are right-aligned, so a money value
belongs to the column whose header shares its right edge. A line that starts with a
date opens a new row, and a line that holds only description text continues the one
above. Anything else (watermark, footer, page furniture) is ignored.
"""

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

from ..ledger import LedgerRow, Statement
from .layouts import Layout, detect_layout

MONEY = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*\.\d{2}$")
LINE_TOLERANCE = 3.0    # points; words within this vertical distance share a line
EDGE_TOLERANCE = 4.0    # points; slack when matching words to column edges

META_PATTERNS = {
    "holder": re.compile(r"Account holder:\s*(.+?)\s+t/a\s+(.+)$"),
    "account": re.compile(r"(?:Account|Wallet):\s*(\S+)"),
    "period": re.compile(r"Period:\s*(.+)$"),
    "opening": re.compile(r"Opening balance:\s*ZMW\s*(\S+)"),
    "closing": re.compile(r"Closing balance:\s*ZMW\s*(\S+)"),
}


class ParseError(ValueError):
    pass


def money(text: str) -> float:
    return float(text.replace(",", "").replace("+", ""))


def _upright(obj: dict) -> bool:
    """False for rotated characters. pdfplumber's own "upright" flag still says True
    for text rotated by 35 degrees, so read the rotation from the text matrix."""
    if obj.get("object_type") != "char":
        return True
    _, b, c, *_ = obj["matrix"]
    return abs(b) < 1e-6 and abs(c) < 1e-6


def _lines(words: list[dict]) -> list[list[dict]]:
    """Group words into visual lines, each sorted left to right."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and w["top"] - lines[-1][0]["top"] <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _header_columns(line: list[dict], layout: Layout) -> dict | None:
    """Edges of each column if this line is the table header, else None."""
    if _text(line) != " ".join(layout.columns):
        return None
    columns, i = {}, 0
    for label in layout.columns:
        n = len(label.split())
        span = line[i:i + n]
        columns[label] = {"x0": span[0]["x0"], "x1": span[-1]["x1"]}
        i += n
    return columns


def _cells(line: list[dict], columns: dict, layout: Layout) -> dict:
    cells = {label: [] for label in layout.columns}
    left = [c for c in layout.columns if c not in layout.numeric]
    for w in line:
        if MONEY.match(w["text"]):
            label = min(layout.numeric, key=lambda c: abs(columns[c]["x1"] - w["x1"]))
            if abs(columns[label]["x1"] - w["x1"]) <= EDGE_TOLERANCE:
                cells[label].append(w["text"])
                continue
        owners = [c for c in left if columns[c]["x0"] - EDGE_TOLERANCE <= w["x0"]]
        cells[owners[-1] if owners else layout.columns[0]].append(w["text"])
    return {label: " ".join(parts) for label, parts in cells.items()}


def _metadata(lines: list[list[dict]]) -> dict:
    meta = {}
    for line in lines:
        text = _text(line)
        for key, pattern in META_PATTERNS.items():
            m = pattern.search(text)
            if m and key not in meta:
                meta[key] = m.groups()
    missing = {"holder", "account", "opening", "closing"} - set(meta)
    if missing:
        raise ParseError(f"Statement header is missing {sorted(missing)}")
    return meta


def _row(cells: dict, layout: Layout, statement_id: str, n: int, page: int) -> LedgerRow:
    stamp = datetime.strptime(cells[layout.date], layout.date_format)
    if layout.signed_amount:
        raw = cells[layout.signed_amount]
        direction = "debit" if raw.startswith("-") else "credit"
        amount = abs(money(raw))
    elif cells["Credit"]:
        direction, amount = "credit", money(cells["Credit"])
    else:
        direction, amount = "debit", money(cells["Debit"])
    return LedgerRow(
        row_id=f"{statement_id}-{n:04d}",
        channel=layout.channel,
        date=f"{stamp:%Y-%m-%d}",
        time=f"{stamp:%H:%M:%S}" if "%H" in layout.date_format else "",
        description=cells[layout.description],
        reference=cells[layout.reference],
        direction=direction,
        amount=amount,
        balance=money(cells["Balance"]),
        page=page,
    )


def _is_date(text: str, layout: Layout) -> bool:
    try:
        datetime.strptime(text, layout.date_format)
        return True
    except ValueError:
        return False


def parse_statement(path: str | Path, statement_id: str | None = None) -> Statement:
    """Read one statement PDF into the standard ledger.

    statement_id defaults to the file name, e.g. MWILA-001_absa.pdf -> MWILA-001-ABSA.
    """
    path = Path(path)
    statement_id = statement_id or path.stem.replace("_", "-").upper()
    with pdfplumber.open(path) as pdf:
        # Drop rotated characters (watermarks) before building words; otherwise a
        # stray watermark letter can fuse onto an amount, e.g. "D5,980.00".
        pages = [page.filter(_upright).extract_words() for page in pdf.pages]
    if not pages or not pages[0]:
        raise ParseError(f"{path.name} has no readable text (a scan needs OCR first)")

    first_page = _lines(pages[0])
    layout = detect_layout(_text(first_page[0]))
    header_at = next((i for i, line in enumerate(first_page)
                      if _header_columns(line, layout)), None)
    if header_at is None:
        raise ParseError(f"No {layout.channel} transaction table found in {path.name}")
    meta = _metadata(first_page[:header_at])

    rows: list[LedgerRow] = []
    for page_no, words in enumerate(pages, start=1):
        columns = None
        for line in _lines(words):
            if columns is None:  # everything above the header is page furniture
                columns = _header_columns(line, layout)
                continue
            cells = _cells(line, columns, layout)
            filled = {label for label, text in cells.items() if text}
            if _is_date(cells[layout.date], layout):
                rows.append(_row(cells, layout, statement_id, len(rows) + 1, page_no))
            elif rows and filled == {layout.description}:
                rows[-1].description += " " + cells[layout.description]

    holder, business = meta["holder"]
    return Statement(
        statement_id=statement_id,
        channel=layout.channel,
        holder=holder,
        business=business,
        account=meta["account"][0],
        period=meta.get("period", ("",))[0],
        opening_balance=money(meta["opening"][0]),
        closing_balance=money(meta["closing"][0]),
        source_file=path.name,
        rows=rows,
    )
