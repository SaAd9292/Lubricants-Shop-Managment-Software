"""Report controller: build a report by key+params and export to PDF/Excel."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.logging_config import get_logger
from ..reports.report_exporter import to_pdf, to_xlsx
from ..services.product_service import ProductService
from ..services.report_service import ReportService
from ..services.taxonomy_service import TaxonomyService

log = get_logger(__name__)


class ReportController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.reports = ReportService(ctx.db)
        self.taxonomy = TaxonomyService(ctx.db)
        self.products = ProductService(ctx.db)
        self.reports_dir = ctx.config.data_root / "reports"

    # -- lookups for filters -----------------------------------------
    def brands(self) -> list[dict]:
        return self.taxonomy.list_brands(active_only=False)

    def all_products(self) -> list[dict]:
        return self.products.list_products(only_active=True, limit=100000)["rows"]

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(int(minor or 0), sym, mu)

    # -- build --------------------------------------------------------
    def build(self, key: str, date_from: str, date_to: str,
              brand_id: int | None = None, product_id: int | None = None) -> dict[str, Any]:
        rs = self.reports
        if key == "daily_sales":
            return rs.daily_sales(date_from)
        if key == "monthly_sales":
            return rs.monthly_sales(int(date_from[:4]), int(date_from[5:7]))
        if key == "profit":
            return rs.profit(date_from, date_to)
        if key == "stock":
            return rs.stock(brand_id=brand_id, product_id=product_id)
        if key == "low_stock":
            return rs.low_stock()
        if key == "purchases":
            return rs.purchases(date_from, date_to)
        if key == "expenses":
            return rs.expenses(date_from, date_to)
        if key == "tax":
            return rs.tax(date_from, date_to)
        raise ValueError(f"Unknown report key: {key}")

    # -- export -------------------------------------------------------
    def export(self, report: dict[str, Any], fmt: str,
               dest: str | None = None) -> tuple[bool, str, str | None]:
        try:
            company = self.ctx.company.get_company()
            if dest is None:
                self.reports_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = str(self.reports_dir / f"{report['key']}_{stamp}.{fmt}")
            if fmt == "pdf":
                path = to_pdf(report, company, dest)
            elif fmt == "xlsx":
                path = to_xlsx(report, company, dest)
            else:
                return False, f"Unknown format: {fmt}", None
            log.info("Exported %s report -> %s", report["key"], path)
            return True, "ok", path
        except Exception as exc:  # pragma: no cover
            log.exception("Report export failed")
            return False, f"Export failed: {exc}", None
