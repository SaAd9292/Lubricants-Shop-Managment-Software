"""PDF sale receipt generator (ReportLab) — 80mm thermal-roll format.

Pure rendering: given a sale dict (header + items) and company settings, it
writes an 80mm-wide receipt to a file path and returns it. No Qt, no database.

The page WIDTH is fixed at 80mm; the HEIGHT is computed from the content so the
receipt ends exactly at the last line (no blank tail wasting roll paper).

White-label: every shop-identity field comes from company_settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ..core.money import format_money

LINE = colors.HexColor("#000000")
MUTED = colors.HexColor("#333333")

PAGE_W = 80 * mm
MARGIN = 4 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
TOP_M = 5 * mm
BOT_M = 6 * mm


def _rule() -> Table:
    t = Table([[""]], colWidths=[CONTENT_W], rowHeights=[2])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def generate_invoice_pdf(*, sale: dict[str, Any], company: dict[str, Any],
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
    title = ParagraphStyle("title", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=9, alignment=TA_CENTER, leading=12, spaceBefore=1)
    center = ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, alignment=TA_CENTER,
                            textColor=MUTED, leading=9)
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8, leading=10.5)
    item = ParagraphStyle("it", parent=ss["Normal"], fontSize=8, leading=9.5)
    item_b = ParagraphStyle("itb", parent=item, fontName="Helvetica-Bold")
    item_r = ParagraphStyle("itr", parent=item, alignment=TA_RIGHT)

    story: list = []

    logo = company.get("logo_path")
    if logo and Path(logo).is_file():
        try:
            img = Image(logo)
            img._restrictSize(28 * mm, 20 * mm)
            img.hAlign = "CENTER"
            story.append(img)
            story.append(Spacer(1, 3))
        except Exception:
            pass

    story.append(Paragraph(company.get("shop_name") or "Penguix", shop))
    bits = []
    if company.get("address"):
        bits.append(company["address"])
    line2 = []
    if company.get("phone"):
        line2.append("Tel: " + company["phone"])
    if company.get("email"):
        line2.append(company["email"])
    if line2:
        bits.append("  |  ".join(line2))
    ids = []
    if company.get("ntn_number"):
        ids.append("NTN: " + company["ntn_number"])
    if company.get("gst_number"):
        ids.append("GST: " + company["gst_number"])
    if ids:
        bits.append("  |  ".join(ids))
    if bits:
        story.append(Paragraph("<br/>".join(bits), center))

    is_void = sale.get("status") == "void"
    story.append(Paragraph("INVOICE - VOID" if is_void else "INVOICE", title))
    story.append(_rule())

    story.append(Paragraph(f"<b>Invoice No:</b> {sale.get('invoice_no', '')}", small))
    story.append(Paragraph(f"<b>Date:</b> {(sale.get('sale_date') or '')[:16]}", small))
    story.append(Paragraph(f"<b>Cashier:</b> {sale.get('cashier_name') or '-'}", small))
    if sale.get("customer_name"):
        story.append(Paragraph(f"<b>Customer:</b> {sale.get('customer_name')}", small))
    pay_txt = sale.get("payment_method") or "-"
    if sale.get("payment_account_name"):
        pay_txt += f" ({sale['payment_account_name']})"
    story.append(Paragraph(f"<b>Payment:</b> {pay_txt}", small))
    story.append(_rule())

    col_l = CONTENT_W * 0.72
    col_r = CONTENT_W - col_l
    rows = [[Paragraph("Item", item_b), Paragraph("Amount", item_r)]]
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINE),
    ]
    r = 1
    for it in sale.get("items", []):
        name = it.get("product_name", "")
        qty = it.get("qty", 0)
        unit = it.get("unit_price_minor", 0)
        ltot = it.get("line_total_minor", 0)
        rows.append([Paragraph(name, item_b), ""])
        cmds.append(("SPAN", (0, r), (1, r)))
        r += 1
        rows.append([Paragraph(f"{qty} x {fmt(unit)}", item), Paragraph(fmt(ltot), item_r)])
        cmds.append(("BOTTOMPADDING", (0, r), (1, r), 4))
        r += 1
    items_tbl = Table(rows, colWidths=[col_l, col_r])
    items_tbl.setStyle(TableStyle(cmds))
    story.append(items_tbl)
    story.append(_rule())

    trows = [["Subtotal", fmt(sale.get("subtotal_minor", 0))]]
    if sale.get("discount_minor"):
        trows.append(["Discount", "- " + fmt(sale["discount_minor"])])
    if sale.get("tax_minor"):
        rate = sale.get("tax_rate_bps", 0) / 100.0
        trows.append([f"{sale.get('tax_label', 'Tax')} {rate:.2f}%", fmt(sale["tax_minor"])])
    trows.append(["Grand Total", fmt(sale.get("grand_total_minor", 0))])
    if str(sale.get("payment_method", "")).lower() == "cash" and sale.get("amount_paid_minor"):
        trows.append(["Paid", fmt(sale["amount_paid_minor"])])
        change = max(0, int(sale["amount_paid_minor"]) - int(sale.get("grand_total_minor", 0)))
        trows.append(["Change", fmt(change)])

    grand_row = next(i for i, r_ in enumerate(trows) if r_[0] == "Grand Total")
    totals_tbl = Table(trows, colWidths=[CONTENT_W * 0.58, CONTENT_W * 0.42])
    totals_tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEABOVE", (0, grand_row), (-1, grand_row), 0.5, LINE),
        ("FONTNAME", (0, grand_row), (-1, grand_row), "Helvetica-Bold"),
        ("FONTSIZE", (0, grand_row), (-1, grand_row), 11),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 6))
    story.append(_rule())
    story.append(Spacer(1, 3))
    footer = ParagraphStyle("f", parent=center, fontSize=8)
    story.append(Paragraph(company.get("invoice_footer") or "Thank you for your business!", footer))

    total_h = 0.0
    for f in story:
        _, h = f.wrap(CONTENT_W, 100000)
        total_h += h
    page_h = max(90 * mm, TOP_M + BOT_M + total_h + 4 * mm)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=(PAGE_W, page_h),
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=TOP_M, bottomMargin=BOT_M,
        title=f"Receipt {sale.get('invoice_no', '')}",
    )
    doc.build(story)
    return str(output_path)
