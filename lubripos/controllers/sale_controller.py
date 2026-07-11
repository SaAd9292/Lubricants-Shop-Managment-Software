"""Sale controller: POS lookups, checkout, history, void.

Checkout is allowed for any authenticated user (admin or cashier). Voiding a
sale is admin-only. Decimal money from the UI is converted to minor units here.
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.product_service import ProductService
from ..services.invoice_service import InvoiceService
from ..services.sale_service import SaleService

log = get_logger(__name__)


class SaleController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.sales = SaleService(ctx.db, ctx.audit)
        self.products = ProductService(ctx.db, ctx.audit)
        self.invoices = InvoiceService(ctx)

    # -- currency / tax ----------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    def tax_info(self) -> dict[str, Any]:
        return self.ctx.company.get_tax()

    # -- POS lookups --------------------------------------------------
    def find_by_barcode(self, barcode: str) -> dict | None:
        return self.products.find_by_barcode(barcode.strip())

    def search_products(self, term: str, limit: int = 50) -> list[dict]:
        return self.products.list_products(search=term, limit=limit)["rows"]

    # -- checkout -----------------------------------------------------
    def checkout(self, *, lines: list[dict[str, Any]], discount: float = 0,
                 payment_method: str = "cash", payment_account_id: int | None = None,
                 amount_paid: float = 0):
        """lines: [{product_id, qty, unit_price (decimal)}]. Returns (ok, msg, summary)."""
        _, mu = self.currency()
        items: list[dict[str, Any]] = []
        try:
            for ln in lines:
                item = {"product_id": ln["product_id"], "qty": int(ln["qty"])}
                if ln.get("unit_price") is not None:
                    item["unit_price_minor"] = money.to_minor(ln["unit_price"], mu)
                items.append(item)
            discount_minor = money.to_minor(discount or 0, mu)
            amount_paid_minor = money.to_minor(amount_paid or 0, mu)
        except (ValueError, ArithmeticError, KeyError):
            return False, "Invalid cart data (check quantities, prices, amounts).", None

        try:
            user = current_session.require_authenticated()
            if discount_minor > 0 and not current_session.can("sale.discount"):
                return False, "You do not have permission to give discounts.", None
            summary = self.sales.create_sale(
                items=items, cashier_id=user.id, cashier_name=user.full_name or user.username,
                discount_minor=discount_minor, payment_method=payment_method,
                payment_account_id=payment_account_id,
                amount_paid_minor=amount_paid_minor, user_id=user.id,
            )
            return True, "ok", summary
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Checkout failed")
            return False, f"Unexpected error: {exc}", None

    # -- history ------------------------------------------------------
    def list(self, **kwargs) -> dict[str, Any]:
        return self.sales.list_sales(**kwargs)

    def get(self, sale_id: int) -> dict[str, Any]:
        return self.sales.get_sale(sale_id)

    def generate_pdf(self, sale_id: int, dest=None):
        """Render an invoice PDF. Returns (ok, msg, path)."""
        try:
            path = self.invoices.generate(sale_id, dest)
            return True, "ok", path
        except Exception as exc:  # pragma: no cover
            log.exception("PDF generation failed")
            return False, f"Could not create PDF: {exc}", None

    def void(self, sale_id: int):
        try:
            user = current_session.require_permission("sale.void")
            self.sales.void_sale(sale_id, user_id=user.id)
            return True, "ok", sale_id
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Void failed")
            return False, f"Unexpected error: {exc}", None
