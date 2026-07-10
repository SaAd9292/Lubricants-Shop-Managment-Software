"""Product controller: bridges the products view and the service layer.

Responsibilities:
  * Convert decimal price input <-> integer minor units using shop currency.
  * Convert markup percent <-> basis points.
  * Enforce admin-only writes (defense-in-depth; the nav already hides the
    page from cashiers).
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.product_service import ProductService
from ..services.taxonomy_service import TaxonomyService

log = get_logger(__name__)


class ProductController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.products = ProductService(ctx.db, ctx.audit)
        self.taxonomy = TaxonomyService(ctx.db, ctx.audit)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    # -- reads --------------------------------------------------------
    def list(self, **kwargs) -> dict[str, Any]:
        return self.products.list_products(**kwargs)

    def get(self, product_id: int) -> dict[str, Any]:
        return self.products.get(product_id)

    def categories(self) -> list[dict]:
        return self.taxonomy.list_categories()

    def brands(self) -> list[dict]:
        return self.taxonomy.list_brands()

    def find_by_barcode(self, barcode: str) -> dict | None:
        """Used by the product form to warn about a duplicate barcode live."""
        bc = (barcode or "").strip()
        if not bc:
            return None
        return self.products.find_by_barcode(bc, only_active=False)

    # -- writes -------------------------------------------------------
    def add_category(self, name: str) -> tuple[bool, str, int | None]:
        return self._guarded(lambda uid: self.taxonomy.add_category(name, user_id=uid))

    def add_brand(self, name: str) -> tuple[bool, str, int | None]:
        return self._guarded(lambda uid: self.taxonomy.add_brand(name, user_id=uid))

    def save(self, form: dict[str, Any], product_id: int | None = None) -> tuple[bool, str, int | None]:
        """form prices are decimals (str/float); convert to minor units here."""
        _, mu = self.currency()
        data = dict(form)
        try:
            if "purchase_price" in data:
                data["purchase_price_minor"] = money.to_minor(data.pop("purchase_price"), mu)
            if "sale_price" in data:
                data["sale_price_minor"] = money.to_minor(data.pop("sale_price"), mu)
            # Markup comes from the form as a percent (e.g. 18.5) -> basis points
            # (1850). bps keeps it an exact integer, consistent with tax storage.
            if "markup" in data:
                data["markup_bps"] = int(round(float(data.pop("markup")) * 100))
        except (ValueError, ArithmeticError):
            return False, "Prices/markup must be valid numbers.", None

        def op(uid):
            if product_id is None:
                return self.products.create(data, user_id=uid)
            self.products.update(product_id, data, user_id=uid)
            return product_id

        return self._guarded(op)

    def adjust_stock(self, product_id: int, new_qty: int,
                     reason: str) -> tuple[bool, str, int | None]:
        return self._guarded(
            lambda uid: self.products.adjust_stock(product_id, new_qty, reason, user_id=uid))

    def delete(self, product_id: int) -> tuple[bool, str, int | None]:
        return self._guarded(
            lambda uid: self.products.set_active(product_id, False, user_id=uid) or product_id
        )

    def reactivate(self, product_id: int) -> tuple[bool, str, int | None]:
        return self._guarded(
            lambda uid: self.products.set_active(product_id, True, user_id=uid) or product_id
        )

    # -- internal -----------------------------------------------------
    def _guarded(self, op) -> tuple[bool, str, int | None]:
        """Run a write op under admin-role enforcement, mapping errors to UI."""
        try:
            user = current_session.require_role("admin")
            result_id = op(user.id)
            return True, "ok", result_id
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover - unexpected
            log.exception("Product operation failed")
            return False, f"Unexpected error: {exc}", None
