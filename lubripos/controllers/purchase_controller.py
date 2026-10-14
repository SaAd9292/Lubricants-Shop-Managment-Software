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
               notes: str | None = None, amount_paid: float | None = None,
               discount: float = 0, tax: float = 0):
        """lines: [{product_id, qty, unit_cost (decimal), discount (decimal)?}].
        discount (decimal) = whole-bill discount on top of any per-line discounts.
        tax (decimal) = advance/withholding tax as an actual amount, added after
        the discount. amount_paid (decimal) = paid to the supplier now; None means
        paid in full."""
        _, mu = self.currency()
        items: list[dict[str, Any]] = []
        try:
            for ln in lines:
                items.append({
                    "product_id": ln["product_id"],
                    "qty": int(ln["qty"]),
                    "unit_cost_minor": money.to_minor(ln["unit_cost"], mu),
                    "discount_minor": money.to_minor(ln.get("discount") or 0, mu),
                })
            amount_paid_minor = (None if amount_paid is None
                                 else money.to_minor(amount_paid, mu))
            discount_minor = money.to_minor(discount or 0, mu)
            tax_minor = money.to_minor(tax or 0, mu)
        except (ValueError, ArithmeticError, KeyError):
            return False, "Invalid line data (check quantities, costs, discounts, tax, amount paid).", None

        def op(uid):
            return self.purchases.create_purchase(
                supplier_id=supplier_id, items=items, purchase_date=purchase_date,
                supplier_invoice_no=supplier_invoice_no, notes=notes,
                amount_paid_minor=amount_paid_minor, discount_minor=discount_minor,
                tax_minor=tax_minor, user_id=uid,
            )
        return self._guarded(op)

    def edit(self, purchase_id: int, *, supplier_id=None, purchase_date=None,
             supplier_invoice_no=None, notes=None, amount_paid=None,
             discount=None, tax=None):
        """Edit a purchase header (supplier/date/bill no/note/amount paid/bill
        discount/advance tax) — admin only. Decimal amounts. Returns
        (ok, msg, purchase_id)."""
        _, mu = self.currency()
        try:
            amt = None if amount_paid is None else money.to_minor(amount_paid, mu)
            disc = None if discount is None else money.to_minor(discount, mu)
            tx = None if tax is None else money.to_minor(tax, mu)
        except (ValueError, ArithmeticError):
            return False, "Invalid amount.", None

        def op(uid):
            self.purchases.update_purchase(
                purchase_id, supplier_id=supplier_id, purchase_date=purchase_date,
                supplier_invoice_no=supplier_invoice_no, notes=notes,
                amount_paid_minor=amt, discount_minor=disc, tax_minor=tx, user_id=uid)
            return purchase_id
        return self._guarded(op)

    def create_return(self, *, supplier_id: int | None, lines: list[dict[str, Any]],
                      purchase_id: int | None = None, return_date: str | None = None,
                      notes: str | None = None):
        """Return goods to a supplier (debit note) — admin only. lines:
        [{product_id, qty, unit_cost (decimal)}]. Reduces stock and the supplier
        payable. Returns (ok, msg, {return_id, total_minor})."""
        _, mu = self.currency()
        items: list[dict[str, Any]] = []
        try:
            for ln in lines:
                items.append({
                    "product_id": ln["product_id"],
                    "qty": int(ln["qty"]),
                    "unit_cost_minor": money.to_minor(ln["unit_cost"], mu),
                })
        except (ValueError, ArithmeticError, KeyError):
            return False, "Invalid line data (check quantities and costs).", None

        def op(uid):
            return self.purchases.create_purchase_return(
                supplier_id=supplier_id, items=items, purchase_id=purchase_id,
                return_date=return_date, notes=notes, user_id=uid)
        return self._guarded(op)

    def list_returns(self, **kwargs):
        return self.purchases.list_purchase_returns(**kwargs)

    def reverse_return(self, return_id: int):
        return self._guarded(
            lambda uid: self.purchases.reverse_purchase_return(return_id, user_id=uid)
            or return_id)

    def delete(self, purchase_id: int):
        """Permanently delete a purchase and reverse its stock (admin only). The
        UI also requires the admin's password before calling this."""
        return self._guarded(
            lambda uid: self.purchases.delete_purchase(purchase_id, user_id=uid)
            or purchase_id)

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Purchase operation failed")
            return False, f"Unexpected error: {exc}", None
