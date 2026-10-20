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
        tax_minor: int = 0,
        user_id: int | None = None,
    ) -> int:
        """items: list of {product_id, qty, unit_cost_minor, discount_minor?}.

        discount_minor = a whole-bill discount, on top of any per-line discounts,
        subtracted from the line subtotal.
        tax_minor = advance/withholding tax charged on the bill, an ACTUAL amount
        (not a percentage), ADDED after the discount. Like the bill discount it is
        a general bill-level charge, so it does NOT change any product's unit cost.
        total = subtotal - discount + tax.
        amount_paid_minor = how much is paid to the supplier at purchase time.
        None means paid in full (no payable). A partial payment (< total) needs
        a supplier so the remaining balance can be attributed to someone."""
        norm = self._validate_items(items)
        subtotal = sum(line["line_total_minor"] for line in norm)
        discount_minor = max(0, int(discount_minor or 0))
        tax_minor = max(0, int(tax_minor or 0))
        if discount_minor > subtotal:
            raise ValidationError("The bill discount cannot exceed the subtotal.")
        total = subtotal - discount_minor + tax_minor
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
                "purchase_date, discount_minor, tax_minor, total_minor, "
                "amount_paid_minor, notes, created_by) "
                "VALUES (?,?,COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')),?,?,?,?,?,?)",
                (supplier_id, supplier_invoice_no, purchase_date, discount_minor,
                 tax_minor, total, amount_paid_minor, notes, user_id),
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

    def update_purchase(self, purchase_id: int, *, supplier_id: int | None = None,
                        purchase_date: str | None = None,
                        supplier_invoice_no: str | None = None,
                        notes: str | None = None,
                        amount_paid_minor: int | None = None,
                        discount_minor: int | None = None,
                        tax_minor: int | None = None,
                        user_id: int | None = None) -> None:
        """Edit a purchase's HEADER only — supplier, date, bill number, note,
        amount paid, and the bill-level discount / advance tax. Line items
        (products/qty/cost) are NOT editable here because they moved stock and
        re-priced products; to change those, delete the purchase (which reverses
        the stock) and re-enter it. Any field left None is unchanged.

        Editing the discount or tax recomputes the total from the line subtotal
        (total = subtotal - discount + tax); the amount paid is then re-validated
        against the new total."""
        row = self.db.query_one("SELECT * FROM purchases WHERE id = ?", (purchase_id,))
        if row is None:
            raise NotFoundError(f"Purchase {purchase_id} not found")
        # the line subtotal (sum of per-line net totals) is the stable base that
        # the bill discount/tax adjust; derive the total from it so an edit can't
        # drift from the recorded lines.
        subtotal = self.db.query_one(
            "SELECT COALESCE(SUM(line_total_minor),0) AS s FROM purchase_items "
            "WHERE purchase_id = ?", (purchase_id,))["s"]
        cur_disc = row["discount_minor"] if "discount_minor" in row.keys() else 0
        cur_tax = row["tax_minor"] if "tax_minor" in row.keys() else 0
        new_disc = cur_disc if discount_minor is None else max(0, int(discount_minor))
        new_tax = cur_tax if tax_minor is None else max(0, int(tax_minor))
        if new_disc > subtotal:
            raise ValidationError("The bill discount cannot exceed the subtotal.")
        total = subtotal - new_disc + new_tax
        new_supplier = row["supplier_id"] if supplier_id is None else supplier_id
        new_paid = row["amount_paid_minor"] if amount_paid_minor is None \
            else int(amount_paid_minor)
        if new_paid < 0:
            raise ValidationError("Amount paid cannot be negative.")
        if new_paid > total:
            raise ValidationError("Amount paid cannot exceed the purchase total.")
        if new_paid < total and new_supplier is None:
            raise ValidationError("A credit purchase (amount paid below the total) "
                                  "needs a supplier.")
        if new_supplier is not None and not self.db.query_one(
                "SELECT id FROM suppliers WHERE id = ?", (new_supplier,)):
            raise NotFoundError(f"Supplier {new_supplier} not found")
        if purchase_date is None:
            new_date = row["purchase_date"]
        else:
            pd = purchase_date.strip()
            new_date = f"{pd} 12:00:00" if len(pd) == 10 else pd
        new_inv = row["supplier_invoice_no"] if supplier_invoice_no is None \
            else ((supplier_invoice_no or "").strip() or None)
        new_notes = row["notes"] if notes is None else ((notes or "").strip() or None)
        self.db.execute(
            "UPDATE purchases SET supplier_id=?, purchase_date=?, supplier_invoice_no=?, "
            "notes=?, amount_paid_minor=?, discount_minor=?, tax_minor=?, total_minor=? "
            "WHERE id=?",
            (new_supplier, new_date, new_inv, new_notes, new_paid, new_disc, new_tax,
             total, purchase_id))
        self.audit.record(action="EDIT_PURCHASE", user_id=user_id,
                          entity_type="purchase", entity_id=purchase_id,
                          details={"supplier_id": new_supplier, "amount_paid": new_paid,
                                   "discount": new_disc, "tax": new_tax, "total": total})
        log.info("Edited purchase id=%s (supplier=%s, paid=%s)",
                 purchase_id, new_supplier, new_paid)

    # -- purchase returns (debit notes) -------------------------------
    def create_purchase_return(
        self,
        *,
        supplier_id: int | None,
        items: list[dict[str, Any]],
        purchase_id: int | None = None,
        return_date: str | None = None,
        notes: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Return goods to a supplier (a debit note). items: list of
        {product_id, qty, unit_cost_minor}. Each item's stock is REDUCED and the
        supplier's payable is LOWERED by the total. This is NOT a cash movement.

        A return is refused if it would drive any product's stock below zero (you
        can't send back more than you hold). A supplier is required — the whole
        point is to reduce what is owed to someone."""
        if supplier_id is None:
            raise ValidationError("Select a supplier to return goods to.")
        if not self.db.query_one("SELECT id FROM suppliers WHERE id = ?", (supplier_id,)):
            raise NotFoundError(f"Supplier {supplier_id} not found")
        norm = []
        for it in items or []:
            pid = it.get("product_id")
            qty = int(it.get("qty", 0))
            cost = int(it.get("unit_cost_minor", 0))
            if not pid or qty <= 0:
                continue
            if cost < 0:
                raise ValidationError("Unit cost cannot be negative.")
            norm.append({"product_id": pid, "qty": qty, "unit_cost_minor": cost,
                         "line_total_minor": qty * cost})
        if not norm:
            raise ValidationError("Add at least one product to return.")
        total = sum(line["line_total_minor"] for line in norm)

        with self.db.transaction() as conn:
            # pre-check stock: can't return more than is on hand
            picked = []
            for line in norm:
                prow = conn.execute(
                    "SELECT name, stock_qty FROM products WHERE id = ?",
                    (line["product_id"],)).fetchone()
                if prow is None:
                    raise NotFoundError(f"Product {line['product_id']} not found")
                if line["qty"] > prow["stock_qty"]:
                    raise ValidationError(
                        f"Can't return {line['qty']} of '{prow['name']}' — only "
                        f"{prow['stock_qty']} in stock.")
                picked.append((line, prow["name"]))

            cur = conn.execute(
                "INSERT INTO purchase_returns (supplier_id, purchase_id, return_date, "
                "total_minor, notes, created_by) "
                "VALUES (?,?,COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')),?,?,?)",
                (supplier_id, purchase_id, return_date, total, notes, user_id))
            return_id = cur.lastrowid

            for line, name in picked:
                conn.execute(
                    "INSERT INTO purchase_return_items (return_id, product_id, "
                    "product_name, qty, unit_cost_minor, line_total_minor) "
                    "VALUES (?,?,?,?,?,?)",
                    (return_id, line["product_id"], name, line["qty"],
                     line["unit_cost_minor"], line["line_total_minor"]))
                conn.execute(
                    "UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                    (line["qty"], line["product_id"]))

        self.audit.record(action="PURCHASE_RETURN", user_id=user_id,
                          entity_type="purchase_return", entity_id=return_id,
                          details={"supplier_id": supplier_id, "lines": len(norm),
                                   "total_minor": total})
        log.info("Recorded purchase return id=%s supplier=%s lines=%d total_minor=%d",
                 return_id, supplier_id, len(norm), total)
        return {"return_id": return_id, "total_minor": total}

    def reverse_purchase_return(self, return_id: int, *,
                                user_id: int | None = None) -> None:
        """Undo a purchase return: restore the stock it removed and delete it (so
        the supplier payable goes back up). Items cascade-delete with the row."""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT id FROM purchase_returns WHERE id = ?",
                               (return_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"Purchase return {return_id} not found")
            items = conn.execute(
                "SELECT product_id, qty FROM purchase_return_items WHERE return_id = ?",
                (return_id,)).fetchall()
            for it in items:
                if it["product_id"] is not None:
                    conn.execute(
                        "UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?",
                        (it["qty"], it["product_id"]))
            conn.execute("DELETE FROM purchase_returns WHERE id = ?", (return_id,))
        self.audit.record(action="REVERSE_PURCHASE_RETURN", user_id=user_id,
                          entity_type="purchase_return", entity_id=return_id,
                          details={"lines": len(items)})
        log.warning("Reversed purchase return id=%s; stock restored (%d lines)",
                    return_id, len(items))

    def list_purchase_returns(self, *, supplier_id: int | None = None,
                             date_from: str | None = None,
                             date_to: str | None = None) -> dict[str, Any]:
        clauses, params = [], []
        if supplier_id:
            clauses.append("pr.supplier_id = ?"); params.append(supplier_id)
        if date_from:
            clauses.append("pr.return_date >= ?"); params.append(date_from)
        if date_to:
            clauses.append("pr.return_date <= ?"); params.append(date_to + " 23:59:59")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = [dict(r) for r in self.db.query(
            f"""SELECT pr.id, substr(pr.return_date,1,16) AS date, pr.total_minor,
                   COALESCE(s.name,'(removed)') AS supplier_name, pr.notes,
                   (SELECT COUNT(*) FROM purchase_return_items i WHERE i.return_id = pr.id) AS lines
                FROM purchase_returns pr
                LEFT JOIN suppliers s ON s.id = pr.supplier_id
                {where} ORDER BY pr.return_date DESC, pr.id DESC""", tuple(params))]
        return {"rows": rows, "total": sum(r["total_minor"] for r in rows)}

    def get_purchase_return(self, return_id: int) -> dict[str, Any]:
        """One purchase return with its line items (for the detail/edit view)."""
        head = self.db.query_one(
            """SELECT pr.id, pr.supplier_id, pr.purchase_id, pr.return_date,
                   pr.total_minor, pr.notes,
                   COALESCE(s.name,'(removed)') AS supplier_name
               FROM purchase_returns pr
               LEFT JOIN suppliers s ON s.id = pr.supplier_id
               WHERE pr.id = ?""", (return_id,))
        if head is None:
            raise NotFoundError(f"Purchase return {return_id} not found")
        items = [dict(r) for r in self.db.query(
            "SELECT product_id, product_name, qty, unit_cost_minor, line_total_minor "
            "FROM purchase_return_items WHERE return_id = ? ORDER BY id", (return_id,))]
        out = dict(head)
        out["items"] = items
        return out

    def update_purchase_return(self, return_id: int, *,
                               return_date: str | None = None,
                               notes: str | None = None,
                               user_id: int | None = None) -> None:
        """Edit a purchase return's header (date / note) — NOT its quantities, so
        stock and the supplier payable are untouched. To change the items,
        reverse the return and record a fresh one."""
        if not self.db.query_one("SELECT id FROM purchase_returns WHERE id = ?",
                                 (return_id,)):
            raise NotFoundError(f"Purchase return {return_id} not found")
        sets, params = [], []
        if return_date is not None:
            sets.append("return_date = ?"); params.append(return_date)
        if notes is not None:
            sets.append("notes = ?"); params.append(notes or None)
        if sets:
            params.append(return_id)
            self.db.execute(
                f"UPDATE purchase_returns SET {', '.join(sets)} WHERE id = ?",
                tuple(params))
        self.audit.record(action="EDIT_PURCHASE_RETURN", user_id=user_id,
                          entity_type="purchase_return", entity_id=return_id)
        log.info("Edited purchase return id=%s (header)", return_id)

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
