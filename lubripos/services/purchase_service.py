"""Purchases (stock-in).

Creating a purchase is a SINGLE atomic transaction:
  1. insert the purchase header
  2. insert each line item
  3. increase each product's stock_qty
  4. update each product's purchase_price_minor to the latest unit cost
If anything fails, the whole thing rolls back — stock can never end up
inconsistent with the recorded purchase.

Purchases are immutable history (no edit/delete in this version); corrections
are made by recording a new purchase.
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)


class PurchaseService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- create -------------------------------------------------------
    def create_purchase(
        self,
        *,
        supplier_id: int | None,
        items: list[dict[str, Any]],
        purchase_date: str | None = None,
        supplier_invoice_no: str | None = None,
        notes: str | None = None,
        user_id: int | None = None,
    ) -> int:
        """items: list of {product_id, qty, unit_cost_minor}."""
        norm = self._validate_items(items)
        total = sum(line["line_total_minor"] for line in norm)

        with self.db.transaction() as conn:
            # validate products exist & are active (inside txn for consistency)
            for line in norm:
                row = conn.execute(
                    "SELECT id, is_active FROM products WHERE id = ?",
                    (line["product_id"],),
                ).fetchone()
                if row is None:
                    raise NotFoundError(f"Product {line['product_id']} not found")
                if not row["is_active"]:
                    raise ValidationError("Cannot purchase an inactive product.")

            cur = conn.execute(
                "INSERT INTO purchases (supplier_id, supplier_invoice_no, "
                "purchase_date, total_minor, notes, created_by) "
                "VALUES (?,?,COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')),?,?,?)",
                (supplier_id, supplier_invoice_no, purchase_date, total, notes, user_id),
            )
            purchase_id = cur.lastrowid

            for line in norm:
                conn.execute(
                    "INSERT INTO purchase_items (purchase_id, product_id, qty, "
                    "unit_cost_minor, line_total_minor) VALUES (?,?,?,?,?)",
                    (purchase_id, line["product_id"], line["qty"],
                     line["unit_cost_minor"], line["line_total_minor"]),
                )
                # COSTING DECISION (chosen: last-cost): product cost becomes the
                # latest unit cost paid. To switch to weighted-average instead,
                # change ONLY this UPDATE to blend by quantity, e.g.:
                #   new_avg = (old_qty*old_cost + qty*unit_cost) / (old_qty + qty)
                # No schema change or data migration required.
                conn.execute(
                    "UPDATE products SET stock_qty = stock_qty + ?, "
                    "purchase_price_minor = ? WHERE id = ?",
                    (line["qty"], line["unit_cost_minor"], line["product_id"]),
                )

        self.audit.record(action="PURCHASE", user_id=user_id, entity_type="purchase",
                          entity_id=purchase_id,
                          details={"supplier_id": supplier_id, "lines": len(norm),
                                   "total_minor": total})
        log.info("Recorded purchase id=%s lines=%d total_minor=%d",
                 purchase_id, len(norm), total)
        return purchase_id

    # -- reads --------------------------------------------------------
    def list_purchases(
        self,
        *,
        supplier_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort_dir: str = "desc",
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses, params = [], []
        if supplier_id:
            clauses.append("p.supplier_id = ?")
            params.append(supplier_id)
        if date_from:
            clauses.append("p.purchase_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("p.purchase_date <= ?")
            params.append(date_to + " 23:59:59")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM purchases p {where}", tuple(params)
        )["n"]
        rows = self.db.query(
            f"""SELECT p.*, s.name AS supplier_name,
                   (SELECT COUNT(*) FROM purchase_items pi WHERE pi.purchase_id = p.id) AS line_count,
                   (SELECT COALESCE(SUM(qty),0) FROM purchase_items pi WHERE pi.purchase_id = p.id) AS total_qty
                FROM purchases p
                LEFT JOIN suppliers s ON s.id = p.supplier_id
                {where} ORDER BY p.purchase_date {direction}, p.id {direction}
                LIMIT ? OFFSET ?""",
            (*params, int(limit), int(offset)),
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def get_purchase(self, purchase_id: int) -> dict[str, Any]:
        head = self.db.query_one(
            "SELECT p.*, s.name AS supplier_name FROM purchases p "
            "LEFT JOIN suppliers s ON s.id = p.supplier_id WHERE p.id = ?",
            (purchase_id,),
        )
        if not head:
            raise NotFoundError(f"Purchase {purchase_id} not found")
        items = self.db.query(
            "SELECT pi.*, pr.name AS product_name, pr.barcode "
            "FROM purchase_items pi LEFT JOIN products pr ON pr.id = pi.product_id "
            "WHERE pi.purchase_id = ? ORDER BY pi.id",
            (purchase_id,),
        )
        result = dict(head)
        result["items"] = [dict(i) for i in items]
        return result

    # -- helpers ------------------------------------------------------
    def _validate_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            raise ValidationError("Add at least one product line.")
        norm = []
        for it in items:
            pid = it.get("product_id")
            qty = int(it.get("qty", 0))
            cost = int(it.get("unit_cost_minor", 0))
            if not pid:
                raise ValidationError("Each line must have a product selected.")
            if qty <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            if cost < 0:
                raise ValidationError("Unit cost cannot be negative.")
            norm.append({
                "product_id": pid, "qty": qty, "unit_cost_minor": cost,
                "line_total_minor": qty * cost,
            })
        return norm
