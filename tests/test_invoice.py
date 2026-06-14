"""Headless test: invoice PDF generation (ReportLab)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.reports.invoice_pdf import generate_invoice_pdf
from lubripos.services.company_service import CompanyService
from lubripos.services.invoice_service import InvoiceService
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def _pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
    except Exception:
        return ""


def main() -> int:
    tmp = Path(tempfile.mkdtemp())

    print("\n[invoice] pure generator")
    company = {"shop_name": "Afridi Lubricants", "address": "Karkhano Market, Peshawar",
               "phone": "0300-1234567", "currency_symbol": "Rs", "currency_minor_units": 100,
               "gst_number": "17-XYZ", "invoice_footer": "Thank you for shopping!"}
    sale = {
        "invoice_no": "INV-000042", "sale_date": "2026-06-13 10:30:00",
        "cashier_name": "Saad", "payment_method": "cash", "status": "completed",
        "subtotal_minor": 600000, "discount_minor": 50000, "tax_label": "GST",
        "tax_rate_bps": 1700, "tax_minor": 93500, "grand_total_minor": 643500,
        "amount_paid_minor": 700000,
        "items": [
            {"product_name": "ZIC X7 5W-30 4L", "qty": 2, "unit_price_minor": 300000, "line_total_minor": 600000},
        ],
    }
    out = tmp / "pure.pdf"
    generate_invoice_pdf(sale=sale, company=company, output_path=out)
    check(out.is_file(), "PDF file created")
    check(out.stat().st_size > 1500, f"PDF non-trivial size ({out.stat().st_size} bytes)")
    txt = _pdf_text(str(out))
    if txt:
        check("Afridi Lubricants" in txt, "PDF contains shop name (white-label)")
        check("INV-000042" in txt, "PDF contains invoice number")
        check("INVOICE" in txt, "PDF contains INVOICE title")
    else:
        print("  (pypdf not available; skipping text-content checks)")

    print("\n[invoice] void marker")
    void_sale = dict(sale, status="void", invoice_no="INV-000043")
    vout = tmp / "void.pdf"
    generate_invoice_pdf(sale=void_sale, company=company, output_path=vout)
    vtxt = _pdf_text(str(vout))
    if vtxt:
        check("VOID" in vtxt, "void invoice shows VOID marker")

    print("\n[invoice] via InvoiceService against real DB")
    cfg = Config(data_root=tmp / "app"); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    CompanyService(ctx.db).update_company({"shop_name": "Khan Oil Store"})
    pid = ProductService(ctx.db).create({"name": "Shell HX7 4L", "sale_price_minor": 27000,
                                         "purchase_price_minor": 22000, "stock_qty": 10})
    s = SaleService(ctx.db).create_sale(items=[{"product_id": pid, "qty": 2}],
                                        cashier_id=1, cashier_name="Saad")
    path = InvoiceService(ctx).generate(s["id"])
    check(Path(path).is_file(), "InvoiceService wrote PDF to default location")
    check(Path(path).name == s["invoice_no"] + ".pdf", "PDF named after invoice number")
    ctx.shutdown()

    p = sum(_r)
    print(f"\n==== {p}/{len(_r)} checks passed ====")
    return 0 if p == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
