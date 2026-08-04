"""PDF receipt for a customer debt repayment (ReportLab) — 80mm thermal roll.

Pure rendering: given a payment dict (from CustomerService.get_payment) and the
company settings, it writes an 80mm-wide receipt to a path and returns it.
No Qt, no database. White-label: shop identity comes from company_settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.money import format_money

LINE = colors.HexColor("#000000")
PAGE_W = 80 * mm
MARGIN = 4 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _rule() -> Table:
    t = Table([[""]], colWidths=[CONTENT_W], rowHeights=[2])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 1),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def generate_payment_receipt_pdf(*, payment: dict[str, Any],
                                 company: dict[str, Any],
                                 output_path: str | Path) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    symbol = company.get("currency_symbol", "Rs")
    mu = company.get("currency_minor_units", 100)

    def fmt(minor: int) -> str:
        return format_money(int(minor or 0), symbol, mu)

    ss = getSampleStyleSheet()
    shop = ParagraphStyle("shop", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=12, alignment=TA_CENTER, leading=14)
    center = ParagraphStyle("center", parent=ss["Normal"], fontSize=8,
                            alignment=TA_CENTER, leading=10)
    title = ParagraphStyle("title", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=10, alignment=TA_CENTER, leading=13)
    normal = ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, leading=12)
    big = ParagraphStyle("big", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=11, alignment=TA_RIGHT, leading=14)

    story: list = [Paragraph(company.get("shop_name") or "Penguix", shop)]
    if company.get("address"):
        story.append(Paragraph(company["address"], center))
    if company.get("phone"):
        story.append(Paragraph("Tel: " + company["phone"], center))
    story += [Spacer(1, 4), Paragraph("PAYMENT RECEIPT", title), Spacer(1, 3), _rule()]

    method = payment.get("method") or "-"
    if payment.get("account_name"):
        method += f"  ({payment['account_name']})"
    rows = [
        ("Receipt No:", f"PMT-{payment['id']:05d}"),
        ("Date:", (payment.get("payment_date") or "")[:16]),
        ("Customer:", payment.get("customer_name") or "-"),
    ]
    if payment.get("customer_phone"):
        rows.append(("Phone:", payment["customer_phone"]))
    rows.append(("Method:", method))
    if payment.get("notes"):
        rows.append(("Note:", payment["notes"]))
    for label, val in rows:
        story.append(Paragraph(f"<b>{label}</b> {val}", normal))

    story += [Spacer(1, 4), _rule(),
              Paragraph("Amount paid:  " + fmt(payment["amount_minor"]), big)]
    bal = int(payment.get("balance_after", 0) or 0)
    due = Paragraph(
        "Amount due:  " + fmt(max(bal, 0))
        + ("   (PAID IN FULL)" if bal <= 0 else ""), big)
    story.append(due)
    story += [Spacer(1, 6), _rule(), Spacer(1, 3),
              Paragraph("Thank you.", center)]

    # size the page HEIGHT to the content so the receipt ends at the last line
    # (no long blank tail wasting roll paper), exactly like the sale receipt.
    top_m, bot_m = 5 * mm, 6 * mm
    total_h = 0.0
    for f in story:
        _, h = f.wrap(CONTENT_W, 100000)
        total_h += h
    page_h = max(70 * mm, top_m + bot_m + total_h + 4 * mm)

    doc = SimpleDocTemplate(str(output_path), pagesize=(PAGE_W, page_h),
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=top_m, bottomMargin=bot_m, title="Payment Receipt")
    doc.build(story)
    return str(output_path)
