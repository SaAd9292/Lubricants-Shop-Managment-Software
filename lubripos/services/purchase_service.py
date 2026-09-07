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
from ..core.money import apply_markup
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
        amount_paid_minor: int | None = None,
        discount_minor: int = 0,
        user_id: int | None = None,
    ) -> int:
        """items: list of {product_id, qty, unit_cost_minor, discount_minor?}.

        discount_minor = a whole-bill discount, on top of any per-line discounts,
        subtracted from the line subtotal to give the payable total.
        amount_paid_minor = how much is paid to the supplier at purchase time.
        None means paid in full (no payable). A partial payment (< total) needs
        a supplier so the remaining balance can be attributed to someone."""
        norm = self._validate_items(items)
        subtotal = sum(line["line_total_minor"] for line in norm)
        discount_minor = max(0, int(discount_minor or 0))
        if discount_minor > subtotal:
            raise ValidationError("The bill discount cannot exceed the subtotal.")
        total = subtotal - discount_minor
        if amount_paid_minor is None:
            amount_paid_minor = total
        amount_paid_minor = int(amount_paid_minor)
        if amount_paid_minor < 0:
            raise ValidationError("Amount paid cannot be negative.")
        if amount_paid_minor > total:
            raise ValidationError("Amount paid cannot exceed the purchase total.")
        if amount_paid_minor < total and supplier_id is None:
            raise ValidationError(
                "Select a supplier for a credit purchase (a payable must be "
                "owed to someone).")

        with self.db.transaction() as conn:
            # Currency minor units drive the rounding step for auto-repricing
            # (round to the nearest whole currency unit).
            mu_row = conn.execute(
                "SELECT currency_minor_units FROM company_settings WHERE id = 1"
            ).fetchone()
            minor_units = mu_row["currency_minor_units"] if mu_row else 100

            # validate products exist & are active (inside txn for consistency)
            # and remember each product's markup for the auto-reprice below.
            markups: dict[int, int] = {}
            for line in norm:
                row = conn.execute(
                    "SELECT id, is_active, markup_bps FROM products WHERE id = ?",
                    (line["product_id"],),
                ).fetchone()
                if row is None:
                    raise NotFoundError(f"Product {line['product_id']} not found")
                if not row["is_active"]:
                    raise ValidationError("Cannot purchase an inactive product.")
                markups[line["product_id"]] = row["markup_bps"] or 0

            cur = conn.execute(
                "INSERT INTO purchases (supplier_id, supplier_invoice_no, "
                "purchase_date, discount_minor, total_minor, amount_paid_minor, "
                "notes, created_by) "
                "VALUES (?,?,COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')),?,?,?,?,?)",
                (supplier_id, supplier_invoice_no, purchase_date, discount_minor,
                 total, amount_paid_minor, notes, user_id),
            )
            purchase_id = cur.lastrowid

            for line in norm:
                conn.execute(
                    "INSERT INTO purchase_items (purchase_id, product_id, qty, "
                    "unit_cost_minor, discount_minor, line_total_minor) "
                    "VALUES (?,?,?,?,?,?)",
                    (purchase_id, line["product_id"], line["qty"],
                     line["unit_cost_minor"], line["discount_minor"],
                     line["line_total_minor"]),
                )
                # COSTING DECISION (chosen: last-cost): product cost becomes the
                # latest unit cost paid. The cost basis uses the DISCOUNTED unit
                # cost — the per-line discount actually lowered what we paid per
                # unit — computed from the net line total (line_total_minor is
                # already qty*cost - line discount) divided by qty and rounded to
                # a whole minor unit. The whole-bill discount is a general saving
                # not attributable to one product, so it does NOT change cost.
                eff_unit_cost = round(line["line_total_minor"] / line["qty"])
                #
                # MARKUP PRICING: if the product carries a markup (> 0), the sale
                # price is auto-derived from the new cost (cost * (1 + markup)),
                # rounded to the nearest whole currency unit. markup 0 means the
                # sale price is manual and left untouched.
                markup = markups.get(line["product_id"], 0)
                if markup > 0:
                    new_sale = apply_markup(
                        eff_unit_cost, markup, round_to_minor=minor_units)
                    conn.execute(
                        "UPDATE products SET stock_qty = stock_qty + ?, "
                        "purchase_price_minor = ?, sale_price_minor = ? WHERE id = ?",
                        (line["qty"], eff_unit_cost, new_sale, line["product_id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE products SET stock_qty = stock_qty + ?, "
                        "purchase_price_minor = ? WHERE id = ?",
                        (line["qty"], eff_unit_cost, line["product_id"]),
                    )

        self.audit.record(action="PURCHASE", user_id=user_id, entity_type="purchase",
                          entity_id=purchase_id,
                          details={"supplier_id": supplier_id, "lines": len(norm),
                                   "total_minor": total})
        log.info("Recorded purchase id=%s lines=%d total_minor=%d",
                 purchase_id, len(norm), total)
        return purchase_id

    def delete_purchase(self, purchase_id: int, *, user_id: int | None = None) -> None:
        """Permanently delete a purchase and reverse the stock it added.

        Safety: if any of the purchased units have since been sold (reversing
        would drive a product's stock below zero), the delete is refused — the
        admin must reverse those sales or adjust stock first. Product cost/sale
        prices that the purchase set are left as-is (the prior values aren't
        stored). Linked supplier payments are kept (their purchase link is
        cleared) so the supplier balance stays correct; only this purchase's
        liability is removed. purchase_items cascade-delete with the row.
        """
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"Purchase {purchase_id} not found")
            items = conn.execute(
                "SELECT product_id, qty FROM purchase_items WHERE purchase_id = ?",
                (purchase_id,)).fetchall()
            # pre-check: reversing must not take any product's stock negative
            for it in items:
                prow = conn.execute(
                    "SELECT name, stock_qty FROM products WHERE id = ?",
                    (it["product_id"],)).fetchone()
                if prow is not None and it["qty"] > prow["stock_qty"]:
                    raise ValidationError(
                        f"Can't delete: '{prow['name']}' has only {prow['stock_qty']} "
                        f"in stock but this purchase added {it['qty']} — some have "
                        "already been sold. Reverse those sales or adjust stock first.")
            for it in items:
                conn.execute(
                    "UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                    (it["qty"], it["product_id"]))
            conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))
        self.audit.record(action="DELETE_PURCHASE", user_id=user_id,
                          entity_type="purchase", entity_id=purchase_id,
                          details={"lines": len(items)})
        log.warning("Deleted purchase id=%s; stock reversed (%d lines)",
                    purchase_id, len(items))

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
            disc = max(0, int(it.get("discount_minor") or 0))
            gross = qty * cost
            if disc > gross:
                raise ValidationError("A line discount cannot exceed its line total.")
            norm.append({
                "product_id": pid, "qty": qty, "unit_cost_minor": cost,
                "discount_minor": disc,
                "line_total_minor": gross - disc,
            })
        return norm
