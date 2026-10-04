"""Sales / checkout.

Creating a sale is a SINGLE atomic transaction:
  1. validate every line (active product, qty > 0, enough stock)
  2. snapshot product name / barcode / unit price / unit cost onto each line
     so the invoice and profit figures never change if the product is later
     edited or retired
  3. apply discount and tax (snapshotting the tax label + rate at sale time)
  4. allocate a sequential invoice number (per-shop counter in app_meta)
  5. insert the sale + line items
  6. decrement product stock
If anything fails (e.g. insufficient stock) the whole sale rolls back: no
invoice, no stock change.

Voiding a completed sale (admin) restores stock in a single transaction and
marks the sale 'void' (kept for audit; never hard-deleted).

Money is in integer minor units throughout. Tax rate is basis points.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.exceptions import InsufficientStockError, NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..core.money import apply_tax
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)


def _norm_return_date(value: str | None) -> str:
    """Normalise a caller-supplied return date to a full 'YYYY-MM-DD HH:MM:SS'
    timestamp. A date-only value keeps the current wall-clock time so same-day
    ordering stays natural; None means 'now'."""
    now = datetime.now()
    if not value:
        return now.strftime("%Y-%m-%d %H:%M:%S")
    v = value.strip()
    if len(v) == 10:   # date only -> attach the current time
        return f"{v} {now.strftime('%H:%M:%S')}"
    return v


class SaleService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- create -------------------------------------------------------
    def create_sale(
        self,
        *,
        items: list[dict[str, Any]],
        cashier_id: int | None,
        cashier_name: str | None,
        discount_minor: int = 0,
        payment_method: str = "cash",
        payment_account_id: int | None = None,
        amount_paid_minor: int = 0,
        customer_id: int | None = None,
        customer_name: str | None = None,
        notes: str | None = None,
        sale_date: str | None = None,
        allow_negative_stock: bool = False,
        mark_paid_in_full: bool = False,
        down_payment_minor: int = 0,
        down_payment_method: str | None = None,
        down_payment_account_id: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """items: [{product_id, qty, unit_price_minor?}].

        unit_price_minor is optional; if omitted the product's current sale
        price is used. Returns a summary dict (id, invoice_no, totals, change).
        """
        if not items:
            raise ValidationError("Cart is empty.")
        if discount_minor < 0:
            raise ValidationError("Discount cannot be negative.")

        with self.db.transaction() as conn:
            lines = self._resolve_lines(conn, items,
                                        allow_negative=allow_negative_stock)
            subtotal = sum(ln["line_total_minor"] for ln in lines)

            if discount_minor > subtotal:
                raise ValidationError("Discount cannot exceed the subtotal.")
            net = subtotal - discount_minor

            # Read tax config LIVE at sale time, then snapshot it onto the sale
            # row below. This keeps every historical invoice correct even if the
            # shop later changes its GST rate, label, or turns tax off entirely.
            tax = conn.execute("SELECT * FROM tax_settings WHERE id = 1").fetchone()
            tax_enabled = bool(tax["tax_enabled"]) if tax else False
            tax_label = tax["tax_label"] if tax else "GST"
            tax_rate_bps = tax["tax_rate_bps"] if tax else 0
            tax_inclusive = bool(tax["tax_inclusive"]) if tax else False

            if tax_enabled and tax_rate_bps > 0:
                # Inclusive: the net already contains tax, so the grand total is
                # just the net (tax_minor is the portion backed out, for reports).
                # Exclusive: tax is added on top of the net.
                _, tax_minor = apply_tax(net, tax_rate_bps, inclusive=tax_inclusive)
                grand_total = net if tax_inclusive else net + tax_minor
            else:
                tax_rate_bps, tax_minor, grand_total = 0, 0, net

            # Historical cash bills are already settled: record them paid in full
            # so amount_paid matches the grand total regardless of the tax config.
            if mark_paid_in_full:
                amount_paid_minor = grand_total

            invoice_no = self._next_invoice_no(conn)

            # Snapshot the receiving account's NAME so the invoice/reports survive
            # the account later being renamed or deleted.
            account_name = None
            if payment_account_id:
                acc = conn.execute(
                    "SELECT name FROM payment_accounts WHERE id = ?",
                    (payment_account_id,)).fetchone()
                if acc is None:
                    raise ValidationError("Selected payment account not found.")
                account_name = acc["name"]

            cur = conn.execute(
                "INSERT INTO sales (invoice_no, sale_date, cashier_id, cashier_name, "
                "subtotal_minor, discount_minor, tax_label, tax_rate_bps, tax_minor, "
                "grand_total_minor, payment_method, payment_account_id, "
                "payment_account_name, amount_paid_minor, customer_id, customer_name, "
                "notes, status) "
                "VALUES (?, COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')), "
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'completed')",
                (invoice_no, sale_date, cashier_id, cashier_name, subtotal, discount_minor,
                 tax_label, tax_rate_bps, tax_minor, grand_total, payment_method,
                 payment_account_id, account_name, amount_paid_minor,
                 customer_id, (customer_name or None), (notes or None)),
            )
            sale_id = cur.lastrowid

            for ln in lines:
                conn.execute(
                    "INSERT INTO sale_items (sale_id, product_id, product_name, "
                    "barcode, qty, unit_price_minor, unit_cost_minor, discount_minor, "
                    "line_total_minor) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (sale_id, ln["product_id"], ln["product_name"], ln["barcode"],
                     ln["qty"], ln["unit_price_minor"], ln["unit_cost_minor"],
                     ln.get("discount_minor", 0), ln["line_total_minor"]),
                )
                # Stock may go negative when allow_negative_stock is set (an
                # oversell / back-dated bill): the shop sold warehouse stock
                # before its purchase was booked, so -1 is correct and nets back
                # up when that purchase is entered. Live sales still can't reach
                # here short (guarded in _resolve_lines) unless explicitly allowed.
                conn.execute(
                    "UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                    (ln["qty"], ln["product_id"]),
                )

            # Partial payment: the customer took the goods on credit (Debt) but
            # paid PART of the bill now. Record that part as a payment against
            # their tab so their balance = total - paid, and the cash/bank is
            # counted by its own method (cash hits the till; bank does not).
            dp = int(down_payment_minor or 0)
            if dp > 0 and payment_method == "Debt" and customer_id:
                if dp > grand_total:
                    raise ValidationError("Amount paid now cannot exceed the bill total.")
                dp_acc_name = None
                if down_payment_account_id:
                    _a = conn.execute("SELECT name FROM payment_accounts WHERE id = ?",
                                      (down_payment_account_id,)).fetchone()
                    dp_acc_name = _a["name"] if _a else None
                conn.execute(
                    "INSERT INTO customer_payments (customer_id, sale_id, amount_minor, "
                    "method, account_id, account_name, notes, payment_date, created_by) "
                    "VALUES (?,?,?,?,?,?,?, "
                    "COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')), ?)",
                    (customer_id, sale_id, dp, (down_payment_method or "Cash"),
                     down_payment_account_id, dp_acc_name,
                     f"Paid at sale {invoice_no}", sale_date, user_id))

        # Change is only meaningful for cash tendered; non-cash methods (Bank,
        # EasyPaisa, JazzCash) settle the exact amount, so change is always 0.
        change_minor = max(0, amount_paid_minor - grand_total) if payment_method == "Cash" else 0
        self.audit.record(action="SALE", user_id=user_id, entity_type="sale",
                          entity_id=sale_id,
                          details={"invoice_no": invoice_no, "lines": len(lines),
                                   "grand_total_minor": grand_total})
        log.info("Sale %s created: lines=%d grand_total_minor=%d",
                 invoice_no, len(lines), grand_total)
        return {
            "id": sale_id, "invoice_no": invoice_no, "subtotal_minor": subtotal,
            "discount_minor": discount_minor, "tax_label": tax_label,
            "tax_rate_bps": tax_rate_bps, "tax_minor": tax_minor,
            "grand_total_minor": grand_total, "amount_paid_minor": amount_paid_minor,
            "change_minor": change_minor,
            "short_lines": [ln["product_name"] for ln in lines if ln.get("short")],
        }

    # -- void ---------------------------------------------------------
    def void_sale(self, sale_id: int, *, user_id: int | None = None) -> None:
        with self.db.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if sale is None:
                raise NotFoundError(f"Sale {sale_id} not found")
            if sale["status"] == "void":
                raise ValidationError("Sale is already void.")
            items = conn.execute(
                "SELECT product_id, qty FROM sale_items WHERE sale_id = ?", (sale_id,)
            ).fetchall()
            for it in items:
                if it["product_id"] is not None:
                    conn.execute(
                        "UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?",
                        (it["qty"], it["product_id"]),
                    )
            conn.execute("UPDATE sales SET status = 'void' WHERE id = ?", (sale_id,))
        self.audit.record(action="VOID_SALE", user_id=user_id, entity_type="sale",
                          entity_id=sale_id, details={"invoice_no": sale["invoice_no"]})
        log.warning("Sale id=%s (%s) voided; stock restored", sale_id, sale["invoice_no"])

    def create_return(self, sale_id: int, lines: list[dict[str, Any]], *,
                      user_id: int | None = None, notes: str = "",
                      return_date: str | None = None,
                      credit_customer_id: int | None = None) -> dict[str, Any]:
        """Return specific quantities from a completed sale.

        lines: [{sale_item_id, qty}]. Each returned quantity is restored to
        product stock and recorded in the returns ledger, capped at what is
        still returnable (qty - returned_qty). The sale stays 'completed';
        reports net the refund out via the ledger.
        """
        with self.db.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if sale is None:
                raise NotFoundError(f"Sale {sale_id} not found")
            if sale["status"] == "void":
                raise ValidationError("This sale is already fully void.")
            by_id = {r["id"]: r for r in conn.execute(
                "SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()}

            picked = []
            refund = 0
            for ln in lines:
                item = by_id.get(ln.get("sale_item_id"))
                qty = int(ln.get("qty", 0))
                if qty <= 0:
                    continue
                if item is None:
                    raise ValidationError("A return line does not belong to this sale.")
                remaining = item["qty"] - item["returned_qty"]
                if qty > remaining:
                    raise ValidationError(
                        f"Cannot return {qty} of '{item['product_name']}': "
                        f"only {remaining} still returnable.")
                picked.append((item, qty))
                refund += qty * item["unit_price_minor"]
            if not picked:
                raise ValidationError("Select at least one quantity to return.")

            # Refund method: 'Ledger' when the refund is credited to the
            # customer's account (no cash leaves the drawer) instead of paid out.
            ret_method = "Ledger" if credit_customer_id else None
            rdate = _norm_return_date(return_date)
            cur = conn.execute(
                "INSERT INTO sale_returns (sale_id, refund_minor, method, notes, "
                "created_by, return_date) VALUES (?,?,?,?,?,?)",
                (sale_id, refund, ret_method, (notes or None), user_id, rdate))
            return_id = cur.lastrowid
            if credit_customer_id and refund > 0:
                # Credit the refund to the customer's ledger: a positive payment
                # reduces what they owe (or tips them into credit if it exceeds
                # their balance). Non-cash method, so it never touches the till.
                conn.execute(
                    "INSERT INTO customer_payments (customer_id, sale_id, amount_minor, "
                    "method, notes, payment_date, created_by, return_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (credit_customer_id, sale_id, refund, "Return credit",
                     f"Return credit for {sale['invoice_no']}", rdate, user_id,
                     return_id))
            for item, qty in picked:
                conn.execute(
                    "INSERT INTO sale_return_items (return_id, sale_item_id, product_id, "
                    "product_name, qty, unit_price_minor, unit_cost_minor, line_total_minor) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (return_id, item["id"], item["product_id"], item["product_name"], qty,
                     item["unit_price_minor"], item["unit_cost_minor"],
                     qty * item["unit_price_minor"]))
                conn.execute(
                    "UPDATE sale_items SET returned_qty = returned_qty + ? WHERE id = ?",
                    (qty, item["id"]))
                if item["product_id"] is not None:
                    conn.execute(
                        "UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?",
                        (qty, item["product_id"]))

        self.audit.record(action="RETURN", user_id=user_id, entity_type="sale",
                          entity_id=sale_id,
                          details={"return_id": return_id, "refund_minor": refund,
                                   "invoice_no": sale["invoice_no"]})
        log.info("Return recorded for sale=%s refund_minor=%s", sale_id, refund)
        return {"return_id": return_id, "refund_minor": refund}

    def create_no_receipt_return(self, items: list[dict[str, Any]], *,
                                 method: str | None = None, notes: str = "",
                                 user_id: int | None = None,
                                 return_date: str | None = None,
                                 credit_customer_id: int | None = None) -> dict[str, Any]:
        """Record a return with NO original sale (unlinked). items:
        [{product_id, qty, refund_minor}] where refund_minor is the amount to give
        back for that line (the operator decides it — there is no sale to price
        against). Each item's stock is restored; the refund uses the product's
        current cost as the profit snapshot. method = how the money went out."""
        if not items:
            raise ValidationError("Add at least one product to return.")
        with self.db.transaction() as conn:
            picked, refund = [], 0
            for it in items:
                pid = it.get("product_id")
                qty = int(it.get("qty", 0))
                line_refund = int(it.get("refund_minor", 0))
                if not pid or qty <= 0:
                    continue
                if line_refund < 0:
                    raise ValidationError("Refund amount cannot be negative.")
                prow = conn.execute(
                    "SELECT name, purchase_price_minor FROM products WHERE id = ?",
                    (pid,)).fetchone()
                if prow is None:
                    raise NotFoundError(f"Product {pid} not found")
                picked.append((pid, prow["name"], qty, line_refund,
                               prow["purchase_price_minor"]))
                refund += line_refund
            if not picked:
                raise ValidationError("Add at least one product to return.")

            rdate = _norm_return_date(return_date)
            # Credited to a customer's ledger -> method 'Ledger' (no cash out).
            eff_method = "Ledger" if credit_customer_id else (method or None)
            cur = conn.execute(
                "INSERT INTO sale_returns (sale_id, refund_minor, method, notes, "
                "created_by, return_date) VALUES (NULL, ?, ?, ?, ?, ?)",
                (refund, eff_method, (notes or None), user_id, rdate))
            return_id = cur.lastrowid
            if credit_customer_id and refund > 0:
                conn.execute(
                    "INSERT INTO customer_payments (customer_id, amount_minor, method, "
                    "notes, payment_date, created_by, return_id) VALUES (?,?,?,?,?,?,?)",
                    (credit_customer_id, refund, "Return credit",
                     "Return credit (no receipt)", rdate, user_id, return_id))
            for pid, name, qty, line_refund, cost in picked:
                unit_refund = line_refund // qty if qty else 0
                conn.execute(
                    "INSERT INTO sale_return_items (return_id, sale_item_id, "
                    "product_id, product_name, qty, unit_price_minor, "
                    "unit_cost_minor, line_total_minor) VALUES (?,NULL,?,?,?,?,?,?)",
                    (return_id, pid, name, qty, unit_refund, cost, line_refund))
                conn.execute(
                    "UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?",
                    (qty, pid))

        self.audit.record(action="RETURN_NO_RECEIPT", user_id=user_id,
                          entity_type="sale_return", entity_id=return_id,
                          details={"refund_minor": refund, "method": method or "Cash",
                                   "lines": len(picked)})
        log.warning("No-receipt return recorded id=%s refund_minor=%s", return_id, refund)
        return {"return_id": return_id, "refund_minor": refund}

    def list_returns(self, *, date_from: str | None = None,
                     date_to: str | None = None, limit: int = 500,
                     offset: int = 0) -> dict[str, Any]:
        """Return history, newest first, optionally within an inclusive date
        range (by date part). Each row carries the invoice (or '(no receipt)'),
        refund, method, a short item summary, and who recorded it."""
        conds, params = [], []
        if date_from:
            conds.append("substr(r.return_date,1,10) >= ?"); params.append(date_from[:10])
        if date_to:
            conds.append("substr(r.return_date,1,10) <= ?"); params.append(date_to[:10])
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = [dict(x) for x in self.db.query(
            "SELECT r.id, substr(r.return_date,1,16) AS date, "
            "s.invoice_no AS invoice, r.refund_minor AS refund, "
            "COALESCE(r.method,'Cash') AS method, "
            "COALESCE(u.full_name, u.username, '-') AS by_name, "
            "(SELECT COUNT(*) FROM sale_return_items ri WHERE ri.return_id = r.id) AS lines, "
            "(SELECT COALESCE(SUM(ri.qty),0) FROM sale_return_items ri "
            " WHERE ri.return_id = r.id) AS units "
            "FROM sale_returns r "
            "LEFT JOIN sales s ON s.id = r.sale_id "
            "LEFT JOIN users u ON u.id = r.created_by "
            f"{where} ORDER BY r.return_date DESC, r.id DESC LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset))]
        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM sale_returns r {where}", tuple(params))["n"]
        return {"rows": rows, "total": total}

    def return_detail(self, return_id: int) -> dict[str, Any]:
        """One return with its line items, for a confirm/preview before reversing."""
        head = self.db.query_one(
            "SELECT r.id, r.return_date AS return_date_full, "
            "substr(r.return_date,1,16) AS date, s.invoice_no AS invoice, "
            "r.refund_minor AS refund, COALESCE(r.method,'Cash') AS method, "
            "COALESCE(r.notes,'') AS notes "
            "FROM sale_returns r LEFT JOIN sales s ON s.id = r.sale_id WHERE r.id = ?",
            (return_id,))
        if not head:
            raise NotFoundError(f"Return {return_id} not found")
        items = [dict(x) for x in self.db.query(
            "SELECT product_name, qty, line_total_minor FROM sale_return_items "
            "WHERE return_id = ? ORDER BY id", (return_id,))]
        d = dict(head); d["items"] = items
        return d

    def update_return(self, return_id: int, *, return_date: str | None = None,
                      method: str | None = None, notes: str | None = None,
                      user_id: int | None = None) -> dict[str, Any]:
        """Correct a return's metadata only — its date, refund method, and note.
        Quantities and products are deliberately NOT editable here: changing
        those means re-doing stock math, so a wrong quantity is fixed by
        reversing the return and entering it again. Any field left None is
        unchanged."""
        row = self.db.query_one("SELECT * FROM sale_returns WHERE id = ?", (return_id,))
        if row is None:
            raise NotFoundError(f"Return {return_id} not found")
        new_date = row["return_date"] if return_date is None \
            else _norm_return_date(return_date)
        new_method = row["method"] if method is None else ((method or "").strip() or None)
        new_notes = row["notes"] if notes is None else ((notes or "").strip() or None)
        self.db.execute(
            "UPDATE sale_returns SET return_date=?, method=?, notes=? WHERE id=?",
            (new_date, new_method, new_notes, return_id))
        self.audit.record(action="EDIT_RETURN", user_id=user_id,
                          entity_type="sale_return", entity_id=return_id,
                          details={"return_date": new_date, "method": new_method})
        log.info("Edited return id=%s (date=%s, method=%s)",
                 return_id, new_date, new_method)
        return {"return_id": return_id}

    def reverse_return(self, return_id: int, *, user_id: int | None = None) -> dict[str, Any]:
        """Undo a return entirely: pull the restocked quantity back off each
        product, lower the sale line's returned_qty (for linked returns), and
        delete the return + its items. The cash refund reverses automatically
        because Cash-in-Hand is derived from the returns ledger. Audited."""
        with self.db.transaction() as conn:
            head = conn.execute("SELECT * FROM sale_returns WHERE id = ?",
                                (return_id,)).fetchone()
            if head is None:
                raise NotFoundError(f"Return {return_id} not found")
            items = conn.execute(
                "SELECT * FROM sale_return_items WHERE return_id = ?",
                (return_id,)).fetchall()
            for it in items:
                if it["product_id"] is not None:
                    conn.execute(
                        "UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                        (it["qty"], it["product_id"]))
                if it["sale_item_id"] is not None:   # linked: release the returned qty
                    conn.execute(
                        "UPDATE sale_items SET returned_qty = MAX(0, returned_qty - ?) "
                        "WHERE id = ?", (it["qty"], it["sale_item_id"]))
            # If this refund was credited to a customer's ledger, remove that
            # credit too so their balance returns to what it was.
            conn.execute("DELETE FROM customer_payments WHERE return_id = ?", (return_id,))
            conn.execute("DELETE FROM sale_return_items WHERE return_id = ?", (return_id,))
            conn.execute("DELETE FROM sale_returns WHERE id = ?", (return_id,))
        self.audit.record(action="REVERSE_RETURN", user_id=user_id,
                          entity_type="sale_return", entity_id=return_id,
                          details={"refund_minor": head["refund_minor"],
                                   "sale_id": head["sale_id"]})
        log.warning("Return id=%s reversed; stock pulled back, refund undone", return_id)
        return {"return_id": return_id, "refund_minor": head["refund_minor"]}

    # -- reads --------------------------------------------------------
    def list_sales(
        self,
        *,
        search: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        cashier_id: int | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses, params = [], []
        if search:
            # match the invoice number, the note/description (holds the shop's
            # paper bill number), or the customer name
            like = f"%{search.strip()}%"
            clauses.append("(s.invoice_no LIKE ? OR s.notes LIKE ? "
                           "OR s.customer_name LIKE ?)")
            params += [like, like, like]
        if date_from:
            clauses.append("s.sale_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("s.sale_date <= ?")
            params.append(date_to + " 23:59:59")
        if cashier_id:
            clauses.append("s.cashier_id = ?")
            params.append(cashier_id)
        if status:
            clauses.append("s.status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM sales s {where}", tuple(params)
        )["n"]
        rows = self.db.query(
            f"""SELECT s.*,
                   (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.id) AS line_count
                FROM sales s {where}
                ORDER BY s.sale_date DESC, s.id DESC LIMIT ? OFFSET ?""",
            (*params, int(limit), int(offset)),
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def get_by_invoice(self, invoice_no: str) -> dict[str, Any] | None:
        """Look up a full sale (header + items) by its invoice number, or None."""
        row = self.db.query_one(
            "SELECT id FROM sales WHERE invoice_no = ? COLLATE NOCASE", ((invoice_no or "").strip(),))
        return self.get_sale(row["id"]) if row else None

    def get_sale(self, sale_id: int) -> dict[str, Any]:
        head = self.db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
        if not head:
            raise NotFoundError(f"Sale {sale_id} not found")
        items = self.db.query(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale_id,)
        )
        result = dict(head)
        result["items"] = [dict(i) for i in items]
        return result

    # -- helpers ------------------------------------------------------
    def _resolve_lines(self, conn, items: list[dict[str, Any]], *,
                       allow_negative: bool = False) -> list[dict[str, Any]]:
        # merge duplicate product lines (same product scanned twice)
        merged: dict[int, int] = {}
        overrides: dict[int, int] = {}
        discounts: dict[int, int] = {}
        order: list[int] = []
        for it in items:
            pid = it.get("product_id")
            qty = int(it.get("qty", 0))
            if not pid:
                raise ValidationError("Each line must reference a product.")
            if qty <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            if pid not in merged:
                merged[pid] = 0
                order.append(pid)
            merged[pid] += qty
            if it.get("unit_price_minor") is not None:
                overrides[pid] = int(it["unit_price_minor"])
            discounts[pid] = discounts.get(pid, 0) + int(it.get("discount_minor") or 0)

        lines = []
        for pid in order:
            row = conn.execute(
                "SELECT id, name, barcode, sale_price_minor, purchase_price_minor, "
                "stock_qty, is_active FROM products WHERE id = ?", (pid,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Product {pid} not found")
            if not row["is_active"]:
                raise ValidationError(f"'{row['name']}' is inactive and cannot be sold.")
            qty = merged[pid]
            short = qty > row["stock_qty"]
            if short and not allow_negative:
                # Live sales must never oversell. Back-dated history entry passes
                # allow_negative=True: the bill is recorded, stock is still
                # decremented (going negative if a purchase hasn't been keyed
                # yet), and the line is flagged so the UI can surface it.
                raise InsufficientStockError(
                    f"Not enough stock for '{row['name']}': have {row['stock_qty']}, need {qty}."
                )
            unit_price = overrides.get(pid, row["sale_price_minor"])
            if unit_price < 0:
                raise ValidationError("Unit price cannot be negative.")
            gross = qty * unit_price
            line_discount = max(0, int(discounts.get(pid, 0)))
            if line_discount > gross:
                raise ValidationError(
                    f"Discount on '{row['name']}' exceeds its line total.")
            lines.append({
                "product_id": pid, "product_name": row["name"], "barcode": row["barcode"],
                "qty": qty, "unit_price_minor": unit_price,
                "unit_cost_minor": row["purchase_price_minor"],
                "discount_minor": line_discount,
                "line_total_minor": gross - line_discount,
                "short": short,
            })
        return lines

    def _next_invoice_no(self, conn) -> str:
        # Invoice numbers come from a monotonic counter in app_meta ('invoice_seq')
        # rather than the sales row id, so the shop gets clean sequential numbers
        # (INV-000001, INV-000002, ...) with a configurable prefix. This runs
        # INSIDE the sale transaction, so the read-increment-write is atomic and
        # two sales can never collide on the same number (single-process app).
        prefix_row = conn.execute(
            "SELECT invoice_prefix FROM company_settings WHERE id = 1"
        ).fetchone()
        prefix = (prefix_row["invoice_prefix"] if prefix_row else "INV") or "INV"
        conn.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES ('invoice_seq', '0')")
        seq = int(conn.execute(
            "SELECT value FROM app_meta WHERE key = 'invoice_seq'"
        ).fetchone()["value"])
        seq += 1
        conn.execute("UPDATE app_meta SET value = ? WHERE key = 'invoice_seq'", (str(seq),))
        return f"{prefix}-{seq:06d}"
