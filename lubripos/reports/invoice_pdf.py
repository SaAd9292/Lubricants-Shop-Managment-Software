"""PDF invoice generator (ReportLab).

Pure rendering: given a sale dict (header + items) and the company settings,
it writes a professional A4 invoice to a file path and returns it. No Qt, no
database — fully testable headless.

White-label: every shop-identity field comes from company_settings. If a logo
path is set and the file exists, it is placed in the header.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ..core.money import format_money

# Monochrome palette: black text, grey rules, light-grey header fill
# so invoices/reports print cleanly on black-and-white printers.
ACCENT = colors.black
MUTED = colors.HexColor("#555555")
LINE = colors.HexColor("#999999")
HEADER_BG = colors.HexColor("#e6e6e6")


def generate_invoice_pdf(*, sale: dict[str, Any], company: dict[str, Any],
                         output_path: str | Path) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    symbol = company.get("currency_symbol", "Rs")
    mu = company.get("currency_minor_units", 100)

    def fmt(minor: int) -> str:
        return format_money(int(minor or 0), symbol, mu)

    styles = getSampleStyleSheet()
    h_shop = ParagraphStyle("shop", parent=styles["Title"], fontSize=20,
                            textColor=colors.black, spaceAfter=2, alignment=TA_LEFT)
    p_muted = ParagraphStyle("muted", parent=styles["Normal"], fontSize=9,
                             textColor=MUTED, leading=12)
    p_label = ParagraphStyle("label", parent=styles["Normal"], fontSize=10, textColor=MUTED)
    p_title = ParagraphStyle("title", parent=styles["Title"], fontSize=18,
                             textColor=ACCENT, alignment=TA_RIGHT)
    p_center = ParagraphStyle("center", parent=styles["Normal"], alignment=TA_CENTER,
                              textColor=MUTED, fontSize=10)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Invoice {sale.get('invoice_no', '')}",
    )
    story: list = []

    # ---- header: shop identity (left) + INVOICE title (right) ----
    shop_lines = [Paragraph(company.get("shop_name") or "Penguix", h_shop)]
    contact_bits = []
    if company.get("address"):
        contact_bits.append(company["address"])
    line2 = []
    if company.get("phone"):
        line2.append("Tel: " + company["phone"])
    if company.get("email"):
        line2.append(company["email"])
    if line2:
        contact_bits.append("  |  ".join(line2))
    tax_ids = []
    if company.get("ntn_number"):
        tax_ids.append("NTN: " + company["ntn_number"])
    if company.get("gst_number"):
        tax_ids.append("GST: " + company["gst_number"])
    if tax_ids:
        contact_bits.append("  |  ".join(tax_ids))
    if contact_bits:
        shop_lines.append(Paragraph("<br/>".join(contact_bits), p_muted))

    left_cell: list = []
    logo_path = company.get("logo_path")
    if logo_path and Path(logo_path).is_file():
        try:
            img = Image(logo_path)
            img._restrictSize(40 * mm, 22 * mm)
            left_cell.append(img)
            left_cell.append(Spacer(1, 4))
        except Exception:
            pass
    left_cell.extend(shop_lines)

    status = sale.get("status", "completed")
    right_title = "INVOICE" if status != "void" else "INVOICE (VOID)"
    right_cell = [Paragraph(right_title, p_title)]

    header = Table([[left_cell, right_cell]], colWidths=[110 * mm, 64 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 6))
    story.append(_hr())
    story.append(Spacer(1, 8))

    # ---- meta: invoice no / date / cashier / payment ----
    meta_rows = [
        [Paragraph("Invoice No:", p_label), Paragraph(str(sale.get("invoice_no", "")), styles["Normal"]),
         Paragraph("Date:", p_label), Paragraph((sale.get("sale_date") or "")[:16], styles["Normal"])],
        [Paragraph("Cashier:", p_label), Paragraph(sale.get("cashier_name") or "-", styles["Normal"]),
         Paragraph("Payment:", p_label), Paragraph(str(sale.get("payment_method") or "-"), styles["Normal"])],
    ]
    meta_tbl = Table(meta_rows, colWidths=[24 * mm, 63 * mm, 22 * mm, 65 * mm])
    meta_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    # ---- items table ----
    head = ["#", "Item", "Qty", "Unit Price", "Line Total"]
    data = [head]
    for i, it in enumerate(sale.get("items", []), start=1):
        data.append([
            str(i),
            it.get("product_name", ""),
            str(it.get("qty", 0)),
            fmt(it.get("unit_price_minor", 0)),
            fmt(it.get("line_total_minor", 0)),
        ])
    items_tbl = Table(data, colWidths=[10 * mm, 86 * mm, 16 * mm, 31 * mm, 31 * mm], repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, ACCENT),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (1, 0), (1, -1), 8),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 10))

    # ---- totals (right aligned block) ----
    totals = [["Subtotal", fmt(sale.get("subtotal_minor", 0))]]
    if sale.get("discount_minor"):
        totals.append(["Discount", "- " + fmt(sale["discount_minor"])])
    if sale.get("tax_minor"):
        label = f"{sale.get('tax_label', 'Tax')} {sale.get('tax_rate_bps', 0) / 100:.2f}%"
        totals.append([label, fmt(sale["tax_minor"])])
    totals.append(["Grand Total", fmt(sale.get("grand_total_minor", 0))])
    if (sale.get("payment_method") == "cash") and sale.get("amount_paid_minor"):
        totals.append(["Paid", fmt(sale["amount_paid_minor"])])
        change = max(0, int(sale["amount_paid_minor"]) - int(sale.get("grand_total_minor", 0)))
        totals.append(["Change", fmt(change)])

    totals_tbl = Table(totals, colWidths=[40 * mm, 34 * mm], hAlign="RIGHT")
    grand_row = next(i for i, r in enumerate(totals) if r[0] == "Grand Total")
    totals_tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, grand_row), (-1, grand_row), 0.5, LINE),
        ("FONTNAME", (0, grand_row), (-1, grand_row), "Helvetica-Bold"),
        ("FONTSIZE", (0, grand_row), (-1, grand_row), 12),
        ("TEXTCOLOR", (0, grand_row), (-1, grand_row), ACCENT),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 16))
    story.append(_hr())
    story.append(Spacer(1, 6))
    story.append(Paragraph(company.get("invoice_footer") or "Thank you for your business!", p_center))

    doc.build(story)
    return str(output_path)


def _hr():
    t = Table([[""]], colWidths=[174 * mm], rowHeights=[1])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE)]))
    return t
