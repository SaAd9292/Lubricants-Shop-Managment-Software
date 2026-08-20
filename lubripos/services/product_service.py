"""Product catalog: CRUD, search, filtering, sorting, pagination.

Money in/out is in INTEGER minor units; the controller/view convert to and
from decimals at the edge. Search hits the indexed columns (barcode, name)
and joins brand/category for display. Deletes are soft (is_active = 0) so
sales and purchase history remain intact.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

# Whitelist of sortable columns -> actual SQL expression (prevents injection
# via the sort parameter, which originates from clickable table headers).
_SORT_COLUMNS = {
    "name": "p.name",
    "barcode": "p.barcode",
    "brand": "brand_name",
    "category": "category_name",
    "sale_price": "p.sale_price_minor",
    "purchase_price": "p.purchase_price_minor",
    "stock": "p.stock_qty",
    "updated_at": "p.updated_at",
    "sort_order": "brand_name, p.sort_order",   # group by brand, then per-brand order
}

_EDITABLE = {
    "barcode", "name", "brand_id", "category_id", "unit_type",
    "purchase_price_minor", "sale_price_minor", "markup_bps", "stock_qty",
    "min_stock_level", "sort_order",
    "series", "pack_size", "units_per_carton",
}

_SELECT = """
SELECT p.*, b.name AS brand_name, c.name AS category_name
FROM products p
LEFT JOIN brands b     ON b.id = p.brand_id
LEFT JOIN categories c ON c.id = p.category_id
"""


class ProductService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- reads --------------------------------------------------------
    def list_products(
        self,
        *,
        search: str = "",
        category_id: int | None = None,
        brand_id: int | None = None,
        only_active: bool = True,
        inactive_only: bool = False,      # show ONLY deactivated products
        low_stock_only: bool = False,
        has_barcode: str | None = None,   # None / "with" / "without"
        sort_by: str = "name",
        sort_dir: str = "asc",
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        where, params = self._build_where(
            search, category_id, brand_id, only_active, low_stock_only,
            has_barcode, inactive_only
        )
        sort_expr = _SORT_COLUMNS.get(sort_by, "p.name")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM products p {where}", params
        )["n"]

        rows = self.db.query(
            f"{_SELECT} {where} ORDER BY {sort_expr} {direction}, p.id "
            f"LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def get(self, product_id: int) -> dict[str, Any]:
        row = self.db.query_one(f"{_SELECT} WHERE p.id = ?", (product_id,))
        if not row:
            raise NotFoundError(f"Product {product_id} not found")
        return dict(row)

    def find_by_barcode(self, barcode: str, *, only_active: bool = True) -> dict | None:
        sql = f"{_SELECT} WHERE p.barcode = ?"
        if only_active:
            sql += " AND p.is_active = 1"
        row = self.db.query_one(sql, (barcode,))
        return dict(row) if row else None

    # -- writes -------------------------------------------------------
    def create(self, data: dict[str, Any], *, user_id: int | None = None) -> int:
        clean = self._validate(data, creating=True)
        # Column names are interpolated into the SQL string, but this is safe:
        # _validate() keeps only keys from the _EDITABLE whitelist, so no
        # user-controlled text reaches the column list. VALUES are always bound
        # as ? parameters, never interpolated.
        cols = ", ".join(clean)
        placeholders = ", ".join("?" for _ in clean)
        try:
            cur = self.db.execute(
                f"INSERT INTO products ({cols}) VALUES ({placeholders})",
                tuple(clean.values()),
            )
        except sqlite3.IntegrityError as exc:
            raise self._barcode_error(exc, clean.get("barcode"))
        new_id = cur.lastrowid
        if "sort_order" not in clean:
            # append the new product to the END of ITS BRAND's list — each brand
            # is ordered independently and numbered starting from 1.
            brand = clean.get("brand_id")
            if brand is None:
                self.db.execute(
                    "UPDATE products SET sort_order = (SELECT COALESCE(MAX(sort_order),0)+1 "
                    "FROM products WHERE brand_id IS NULL AND id != ?) WHERE id = ?",
                    (new_id, new_id))
            else:
                self.db.execute(
                    "UPDATE products SET sort_order = (SELECT COALESCE(MAX(sort_order),0)+1 "
                    "FROM products WHERE brand_id = ? AND id != ?) WHERE id = ?",
                    (brand, new_id, new_id))
        # baseline price-history entry so 'price list as of' works from day one
        self.db.execute(
            "INSERT INTO product_price_history (product_id, purchase_price_minor, "
            "sale_price_minor, changed_by) VALUES (?,?,?,?)",
            (new_id, clean.get("purchase_price_minor", 0),
             clean.get("sale_price_minor", 0), user_id))
        self.audit.record(action="CREATE", user_id=user_id, entity_type="product",
                          entity_id=new_id, details={"name": clean.get("name")})
        log.info("Created product id=%s name=%r", new_id, clean.get("name"))
        return new_id

    def update(self, product_id: int, data: dict[str, Any],
               *, user_id: int | None = None) -> None:
        current = self.get(product_id)  # raises NotFoundError if missing
        clean = self._validate(data, creating=False)
        if not clean:
            return
        set_clause = ", ".join(f"{k} = ?" for k in clean)
        try:
            self.db.execute(
                f"UPDATE products SET {set_clause} WHERE id = ?",
                (*clean.values(), product_id),
            )
        except sqlite3.IntegrityError as exc:
            raise self._barcode_error(exc, clean.get("barcode"))
        # if a price actually changed, append a price-history row (new effective
        # prices) so old price lists can be reconstructed by date
        if "purchase_price_minor" in clean or "sale_price_minor" in clean:
            new_pp = clean.get("purchase_price_minor", current["purchase_price_minor"])
            new_sp = clean.get("sale_price_minor", current["sale_price_minor"])
            if (new_pp != current["purchase_price_minor"]
                    or new_sp != current["sale_price_minor"]):
                self.db.execute(
                    "INSERT INTO product_price_history (product_id, "
                    "purchase_price_minor, sale_price_minor, changed_by) VALUES (?,?,?,?)",
                    (product_id, new_pp, new_sp, user_id))
        self.audit.record(action="UPDATE", user_id=user_id, entity_type="product",
                          entity_id=product_id, details={"fields": list(clean)})
        log.info("Updated product id=%s fields=%s", product_id, list(clean))

    def set_active(self, product_id: int, active: bool,
                   *, user_id: int | None = None) -> None:
        self.db.execute(
            "UPDATE products SET is_active = ? WHERE id = ?",
            (1 if active else 0, product_id),
        )
        self.audit.record(action="DELETE" if not active else "UPDATE",
                          user_id=user_id, entity_type="product",
                          entity_id=product_id, details={"is_active": bool(active)})
        log.info("Set product id=%s active=%s", product_id, active)

    def hard_delete(self, product_id: int, *, user_id: int | None = None) -> None:
        """Permanently remove a product. Only allowed when it is already
        deactivated AND has no transaction history (never purchased, sold, or
        returned) — otherwise past reports/invoices would lose the record, so we
        refuse and the product stays deactivated instead."""
        product = self.get(product_id)  # raises NotFoundError if missing
        if product["is_active"]:
            raise ValidationError("Deactivate the product before deleting it permanently.")
        refs = self.db.query_one(
            "SELECT (SELECT COUNT(*) FROM sale_items WHERE product_id = ?) "
            "     + (SELECT COUNT(*) FROM purchase_items WHERE product_id = ?) "
            "     + (SELECT COUNT(*) FROM sale_return_items WHERE product_id = ?) AS n",
            (product_id, product_id, product_id))["n"]
        if refs:
            raise ValidationError(
                "This product has purchase or sales history, so it can't be "
                "permanently deleted. Keep it deactivated — that hides it "
                "everywhere while your past reports stay accurate.")
        self.db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.audit.record(action="DELETE", user_id=user_id, entity_type="product",
                          entity_id=product_id,
                          details={"permanent": True, "name": product["name"]})
        log.info("Permanently deleted product id=%s (%s)", product_id, product["name"])

    def adjust_stock(self, product_id: int, new_qty: int, reason: str,
                     *, user_id: int | None = None) -> int:
        """Set a product's stock to a counted/corrected value (stock-take).

        Unlike purchases/sales this is a manual override, so it records the
        before/after and a reason to the audit log for accountability.
        """
        product = self.get(product_id)  # raises NotFoundError if missing
        new_qty = int(new_qty)
        if new_qty < 0:
            raise ValidationError("Stock quantity cannot be negative.")
        old_qty = product["stock_qty"]
        self.db.execute(
            "UPDATE products SET stock_qty = ? WHERE id = ?", (new_qty, product_id))
        self.audit.record(action="ADJUST_STOCK", user_id=user_id, entity_type="product",
                          entity_id=product_id,
                          details={"from": old_qty, "to": new_qty,
                                   "delta": new_qty - old_qty,
                                   "reason": (reason or "").strip()})
        log.info("Adjusted stock product id=%s %s->%s (%s)",
                 product_id, old_qty, new_qty, reason)
        return new_qty

    # -- helpers ------------------------------------------------------
    def _build_where(self, search, category_id, brand_id, only_active, low_stock_only,
                     has_barcode=None, inactive_only=False):
        clauses: list[str] = []
        params: list[Any] = []
        if inactive_only:
            clauses.append("p.is_active = 0")   # ONLY deactivated products
        elif only_active:
            clauses.append("p.is_active = 1")
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(p.name LIKE ? OR p.barcode LIKE ?)")
            params += [like, like]
        if category_id:
            clauses.append("p.category_id = ?")
            params.append(category_id)
        if brand_id:
            clauses.append("p.brand_id = ?")
            params.append(brand_id)
        if low_stock_only:
            clauses.append("p.min_stock_level > 0 AND p.stock_qty <= p.min_stock_level")
        if has_barcode == "with":
            clauses.append("(p.barcode IS NOT NULL AND TRIM(p.barcode) != '')")
        elif has_barcode == "without":
            clauses.append("(p.barcode IS NULL OR TRIM(p.barcode) = '')")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, tuple(params)

    def _validate(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        clean = {k: v for k, v in data.items() if k in _EDITABLE}

        if creating and not (clean.get("name") or "").strip():
            raise ValidationError("Product name is required.")
        if "name" in clean:
            clean["name"] = clean["name"].strip()
            if not clean["name"]:
                raise ValidationError("Product name cannot be empty.")

        # normalise empty barcode to NULL so multiple blanks don't collide
        if "barcode" in clean:
            bc = (clean["barcode"] or "").strip()
            clean["barcode"] = bc or None

        for money_field in ("purchase_price_minor", "sale_price_minor"):
            if money_field in clean and int(clean[money_field]) < 0:
                raise ValidationError("Prices cannot be negative.")
        if "markup_bps" in clean and int(clean["markup_bps"]) < 0:
            raise ValidationError("Markup cannot be negative.")
        for qty_field in ("stock_qty", "min_stock_level"):
            if qty_field in clean and int(clean[qty_field]) < 0:
                raise ValidationError("Quantities cannot be negative.")
        if "units_per_carton" in clean:
            v = clean["units_per_carton"]
            upc = 1 if v in (None, "") else int(v)
            if upc < 1:
                raise ValidationError("Units per carton must be at least 1.")
            clean["units_per_carton"] = upc
        return clean

    @staticmethod
    def _barcode_error(exc: sqlite3.IntegrityError, barcode) -> Exception:
        if "barcode" in str(exc).lower():
            return ValidationError(f"Barcode '{barcode}' is already used by another product.")
        return exc
