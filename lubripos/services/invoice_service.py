"""Invoice service: assemble a sale + shop settings and render a PDF.

Default output location is <data_root>/invoices/<invoice_no>.pdf. A custom
destination (e.g. from a Save As dialog) can be passed instead.
"""
from __future__ import annotations

from pathlib import Path

from ..core.logging_config import get_logger
from ..reports.invoice_pdf import generate_invoice_pdf
from .sale_service import SaleService

log = get_logger(__name__)


class InvoiceService:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.sales = SaleService(ctx.db)
        self.invoices_dir = ctx.config.data_root / "invoices"

    def default_path(self, invoice_no: str) -> Path:
        self.invoices_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in invoice_no if c.isalnum() or c in "-_") or "invoice"
        return self.invoices_dir / f"{safe}.pdf"

    def generate(self, sale_id: int, dest: str | Path | None = None) -> str:
        sale = self.sales.get_sale(sale_id)
        company = self.ctx.company.get_company()
        if dest is None:
            dest = self.default_path(sale["invoice_no"])
        path = generate_invoice_pdf(sale=sale, company=company, output_path=dest)
        log.info("Generated invoice PDF for sale id=%s -> %s", sale_id, path)
        return path
