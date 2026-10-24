"""Render ledgers as statement PDFs in three layouts.

The layouts are neutral and carry no real logos, and every page is watermarked
SYNTHETIC DATA. Categories are not printed; the parser and labeller must recover them.
"""

from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.invariant = 1  # identical bytes for identical input

CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=7, leading=8.5)
TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=13, leading=16)
META = ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=11)

LAYOUTS = {
    "absa": {
        "title": "Business Current Account Statement",
        "issuer": "Bank statement · Absa-style layout · synthetic",
        "id_label": "Account",
        "header": ["Date", "Description", "Reference", "Debit", "Credit", "Balance"],
        "widths": [18, 72, 30, 22, 22, 24],
        "accent": colors.HexColor("#8B1E3F"),
    },
    "mtn": {
        "title": "Mobile Money Transaction Statement",
        "issuer": "Mobile money statement · MTN-style layout · synthetic",
        "id_label": "Wallet",
        "header": ["Date & Time", "Transaction ID", "Details", "Amount (ZMW)", "Balance"],
        "widths": [28, 26, 82, 24, 28],
        "accent": colors.HexColor("#B8860B"),
    },
    "airtel": {
        "title": "Airtel Money Account Statement",
        "issuer": "Mobile money statement · Airtel-style layout · synthetic",
        "id_label": "Wallet",
        "header": ["Date", "Transaction ID", "Type", "Description", "Debit", "Credit", "Balance"],
        "widths": [18, 34, 12, 58, 20, 20, 26],
        "accent": colors.HexColor("#B22222"),
    },
}


def _money(x: float) -> str:
    return f"{x:,.2f}"


def _row(channel: str, r: dict) -> list:
    debit = _money(r["amount"]) if r["direction"] == "debit" else ""
    credit = _money(r["amount"]) if r["direction"] == "credit" else ""
    desc = Paragraph(r["description"].replace("&", "&amp;"), CELL)
    if channel == "absa":
        return [f"{r['ts']:%d/%m/%Y}", desc, r["reference"], debit, credit, _money(r["balance"])]
    if channel == "mtn":
        sign = "-" if r["direction"] == "debit" else "+"
        return [f"{r['ts']:%Y-%m-%d %H:%M:%S}", r["reference"], desc,
                f"{sign}{_money(r['amount'])}", _money(r["balance"])]
    kind = "DR" if r["direction"] == "debit" else "CR"
    return [f"{r['ts']:%d-%b-%Y}", r["reference"], kind, desc, debit, credit,
            _money(r["balance"])]


class _WatermarkCanvas(Canvas):
    """Stamps the watermark last, so the table's row backgrounds can't hide it."""

    def showPage(self):
        self.saveState()
        self.setFont("Helvetica-Bold", 60)
        self.setFillColor(colors.Color(0.5, 0.5, 0.5, alpha=0.15))
        self.translate(A4[0] / 2, A4[1] / 2)
        self.rotate(35)
        self.drawCentredString(0, 0, "SYNTHETIC DATA")
        self.restoreState()
        super().showPage()


def _decorate(footer: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 10 * mm, footer)
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def render_statement(path: Path, channel: str, profile: dict, rows: list[dict],
                     opening: float) -> None:
    layout = LAYOUTS[channel]
    closing = rows[-1]["balance"] if rows else opening
    start = rows[0]["ts"] if rows else None
    end = rows[-1]["ts"] if rows else None
    period = f"{start:%d %b %Y} to {end:%d %b %Y}" if rows else "No transactions"

    story = [
        Paragraph(layout["title"], TITLE),
        Paragraph(layout["issuer"], META),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Account holder:</b> {profile['owner_name']} t/a "
                  f"{profile['business_name'].replace('&', '&amp;')}", META),
        Paragraph(f"<b>{layout['id_label']}:</b> {profile['channels'][channel]} &nbsp;&nbsp; "
                  f"<b>Branch/area:</b> {profile['town']}", META),
        Paragraph(f"<b>Period:</b> {period}", META),
        Paragraph(f"<b>Opening balance:</b> ZMW {_money(opening)} &nbsp;&nbsp; "
                  f"<b>Closing balance:</b> ZMW {_money(closing)}", META),
        Spacer(1, 4 * mm),
    ]
    data = [layout["header"]] + [_row(channel, r) for r in rows]
    table = Table(data, colWidths=[w * mm for w in layout["widths"]], repeatRows=1)
    numeric_from = len(layout["header"]) - (2 if channel == "mtn" else 3)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), layout["accent"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F4F4")]),
        ("ALIGN", (numeric_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(table)

    footer = "Synthetic statement generated for the Insaka prototype. Not a real record."
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"{layout['title']} (synthetic)", author="Insaka generator")
    decorate = _decorate(footer)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate, canvasmaker=_WatermarkCanvas)
