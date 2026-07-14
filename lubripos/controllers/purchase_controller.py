"""Purchase controller: admin-guarded creation, currency conversion, listing."""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.product_service import ProductService
from ..services.purchase_service import PurchaseService
from ..services.supplier_service import SupplierService

log = get_logger(__name__)


class PurchaseController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.purchases = PurchaseService(ctx.db, ctx.audit)
        self.products = ProductService(ctx.db, ctx.audit)
        self.suppliers = SupplierService(ctx.db, ctx.audit)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    # -- lookups for the dialog --------------------------------------
    def active_suppliers(self) -> list[dict]:
        return self.suppliers.list_active_min()

    def search_products(self, term: str, limit: int = 50) -> list[dict]:
        return self.products.list_products(search=term, limit=limit)["rows"]

    # -- reads --------------------------------------------------------
    def list(self, **kwargs) -> dict[str, Any]:
        return self.purchases.list_purchases(**kwargs)

    def get(self, purchase_id: int) -> dict[str, Any]:
        return self.purchases.get_purchase(purchase_id)

    # -- create -------------------------------------------------------
    def create(self, *, supplier_id: int | None, lines: list[dict[str, Any]],
               purchase_date: str | None = None, supplier_invoice_no: str | None = None,
               notes: str | None = None, amount_paid: float | None = None):
        """lines: [{product_id, qty, unit_cost (decimal)}]. Converts cost->minor.
        amount_paid (decimal) = paid to the supplier now; None means paid in full."""
        _, mu = self.currency()
        items: list[dict[str, Any]] = []
        try:
            for ln in lines:
                items.append({
                    "product_id": ln["product_id"],
                    "qty": int(ln["qty"]),
                    "unit_cost_minor": money.to_minor(ln["unit_cost"], mu),
                })
            amount_paid_minor = (None if amount_paid is None
                                 else money.to_minor(amount_paid, mu))
        except (ValueError, ArithmeticError, KeyError):
            return False, "Invalid line data (check quantities, costs, amount paid).", None

        def op(uid):
            return self.purchases.create_purchase(
                supplier_id=supplier_id, items=items, purchase_date=purchase_date,
                supplier_invoice_no=supplier_invoice_no, notes=notes,
                amount_paid_minor=amount_paid_minor, user_id=uid,
            )
        return self._guarded(op)

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Purchase operation failed")
            return False, f"Unexpected error: {exc}", None
