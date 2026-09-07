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
from ..services.taxonomy_service import TaxonomyService
from ..services.customer_service import CustomerService

log = get_logger(__name__)


class SaleController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.sales = SaleService(ctx.db, ctx.audit)
        self.products = ProductService(ctx.db, ctx.audit)
        self.invoices = InvoiceService(ctx)
        self.taxonomy = TaxonomyService(ctx.db)
        self.customers = CustomerService(ctx.db, ctx.audit)

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

    def search_products(self, term: str, category_id: int | None = None,
                        limit: int = 50) -> list[dict]:
        return self.products.list_products(
            search=term, category_id=category_id, limit=limit)["rows"]

    def categories(self) -> list[dict]:
        return self.taxonomy.list_categories()

    def find_by_invoice(self, invoice_no: str) -> dict | None:
        return self.sales.get_by_invoice(invoice_no)

    def search_customers(self, term: str, limit: int = 20) -> list[dict]:
        return self.customers.search_min(term, limit=limit)

    def customer_last_products(self, customer_id: int) -> list[str]:
        return self.customers.last_products(customer_id)

    def customer_products(self, customer_id: int) -> list[dict]:
        return self.customers.purchased_products(customer_id)

    # -- checkout -----------------------------------------------------
    def checkout(self, *, lines: list[dict[str, Any]], discount: float = 0,
                 payment_method: str = "cash", payment_account_id: int | None = None,
                 amount_paid: float = 0, customer_name: str | None = None,
                 customer_phone: str | None = None, notes: str | None = None,
                 allow_oversell: bool = False):
        """lines: [{product_id, qty, unit_price (decimal)}]. Live POS sale, stamped
        today. allow_oversell=True lets stock go negative (item sold from the
        distribution warehouse before its purchase is booked); the POS asks the
        cashier to confirm before setting it. Back-dated paper bills go through
        record_backdated_sale instead. Returns (ok, msg, summary)."""
        _, mu = self.currency()
        items: list[dict[str, Any]] = []
        try:
            for ln in lines:
                item = {"product_id": ln["product_id"], "qty": int(ln["qty"])}
                if ln.get("unit_price") is not None:
                    item["unit_price_minor"] = money.to_minor(ln["unit_price"], mu)
                if ln.get("discount") is not None:
                    item["discount_minor"] = money.to_minor(ln["discount"], mu)
                items.append(item)
            discount_minor = money.to_minor(discount or 0, mu)
            amount_paid_minor = money.to_minor(amount_paid or 0, mu)
        except (ValueError, ArithmeticError, KeyError):
            return False, "Invalid cart data (check quantities, prices, amounts).", None

        try:
            user = current_session.require_authenticated()
            if discount_minor > 0 and not current_session.can("sale.discount"):
                return False, "You do not have permission to give discounts.", None
            # optional customer attach (walk-in stays NULL)
            customer_id = None
            cust_name = (customer_name or "").strip() or None
            if cust_name:
                customer_id = self.customers.find_or_create(
                    cust_name, customer_phone, user_id=user.id)
            # A Debt (credit) sale is unpaid and MUST sit on a customer's tab.
            if payment_method == "Debt" and customer_id is None:
                return (False,
                        "A debt sale needs a customer. Attach one before checkout.",
                        None)
            summary = self.sales.create_sale(
                items=items, cashier_id=user.id, cashier_name=user.full_name or user.username,
                discount_minor=discount_minor, payment_method=payment_method,
                payment_account_id=payment_account_id,
                amount_paid_minor=amount_paid_minor,
                customer_id=customer_id, customer_name=cust_name,
                notes=(notes or "").strip() or None,
                allow_negative_stock=allow_oversell, user_id=user.id,
            )
            return True, "ok", summary
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Checkout failed")
            return False, f"Unexpected error: {exc}", None

    # -- back-dated bulk entry (admin only) ---------------------------
    def record_backdated_sale(self, *, lines: list[dict[str, Any]],
                              sale_date: str, discount: float = 0,
                              payment_method: str = "Cash",
                              customer_id: int | None = None,
                              customer_name: str | None = None,
                              customer_phone: str | None = None,
                              notes: str | None = None):
        """Record one historical paper bill on its real date. Admin-only.

        lines: [{product_id, qty, unit_price (decimal)}]. sale_date is
        'YYYY-MM-DD' (required). payment_method is one of the usual methods;
        'Debt' (credit / udhaar) is unpaid and needs a customer, everything else
        is recorded paid-in-full. Unlike the live POS this never blocks on short
        stock — stock still decrements (flooring at 0 until the matching purchase
        is keyed) and any short line is reported back. Returns (ok, msg, summary)
        where summary['short_lines'] lists any short items.
        """
        try:
            user = current_session.require_role("admin")
        except LubriPosError as exc:
            return False, str(exc), None
        if not sale_date:
            return False, "A sale date is required for a back-dated bill.", None
        if len(sale_date) == 10:                 # date only -> mid-day timestamp
            sale_date = sale_date + " 12:00:00"
        _, mu = self.currency()
        items: list[dict[str, Any]] = []
        try:
            for ln in lines:
                item = {"product_id": ln["product_id"], "qty": int(ln["qty"])}
                if ln.get("unit_price") is not None:
                    item["unit_price_minor"] = money.to_minor(ln["unit_price"], mu)
                items.append(item)
            discount_minor = money.to_minor(discount or 0, mu)
        except (ValueError, ArithmeticError, KeyError):
            return False, "Invalid line data (check quantities and prices).", None

        is_credit = payment_method == "Debt"
        try:
            cust_name = (customer_name or "").strip() or None
            # A picked, already-saved customer wins (keeps their history/balance);
            # otherwise a typed name is matched-or-created.
            if customer_id is None and cust_name:
                customer_id = self.customers.find_or_create(
                    cust_name, customer_phone, user_id=user.id)
            # A credit (udhaar) bill is unpaid and must sit on a customer's tab.
            if is_credit and customer_id is None:
                return (False,
                        "A credit (udhaar) bill needs a customer name.", None)
            summary = self.sales.create_sale(
                items=items, cashier_id=user.id,
                cashier_name=user.full_name or user.username,
                discount_minor=discount_minor, payment_method=payment_method,
                customer_id=customer_id, customer_name=cust_name,
                notes=(notes or "").strip() or None,
                sale_date=sale_date, allow_negative_stock=True,
                mark_paid_in_full=not is_credit, user_id=user.id,
            )
            return True, "ok", summary
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Back-dated sale failed")
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

    def create_return(self, sale_id, lines, notes=""):
        """lines: [{sale_item_id, qty}]. Returns (ok, msg, {return_id, refund_minor})."""
        try:
            user = current_session.require_permission("sale.void")
            data = self.sales.create_return(sale_id, lines, user_id=user.id, notes=notes)
            return True, "ok", data
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Return failed")
            return False, f"Unexpected error: {exc}", None

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
