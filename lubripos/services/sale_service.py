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

from typing import Any

from ..core.exceptions import InsufficientStockError, NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..core.money import apply_tax
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)


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
            lines = self._resolve_lines(conn, items)
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
                "INSERT INTO sales (invoice_no, cashier_id, cashier_name, "
                "subtotal_minor, discount_minor, tax_label, tax_rate_bps, tax_minor, "
                "grand_total_minor, payment_method, payment_account_id, "
                "payment_account_name, amount_paid_minor, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'completed')",
                (invoice_no, cashier_id, cashier_name, subtotal, discount_minor,
                 tax_label, tax_rate_bps, tax_minor, grand_total, payment_method,
                 payment_account_id, account_name, amount_paid_minor),
            )
            sale_id = cur.lastrowid

            for ln in lines:
                conn.execute(
                    "INSERT INTO sale_items (sale_id, product_id, product_name, "
                    "barcode, qty, unit_price_minor, unit_cost_minor, line_total_minor) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (sale_id, ln["product_id"], ln["product_name"], ln["barcode"],
                     ln["qty"], ln["unit_price_minor"], ln["unit_cost_minor"],
                     ln["line_total_minor"]),
                )
                conn.execute(
                    "UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                    (ln["qty"], ln["product_id"]),
                )

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
            clauses.append("s.invoice_no LIKE ?")
            params.append(f"%{search.strip()}%")
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
    def _resolve_lines(self, conn, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # merge duplicate product lines (same product scanned twice)
        merged: dict[int, int] = {}
        overrides: dict[int, int] = {}
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
            if qty > row["stock_qty"]:
                raise InsufficientStockError(
                    f"Not enough stock for '{row['name']}': have {row['stock_qty']}, need {qty}."
                )
            unit_price = overrides.get(pid, row["sale_price_minor"])
            if unit_price < 0:
                raise ValidationError("Unit price cannot be negative.")
            lines.append({
                "product_id": pid, "product_name": row["name"], "barcode": row["barcode"],
                "qty": qty, "unit_price_minor": unit_price,
                "unit_cost_minor": row["purchase_price_minor"],
                "line_total_minor": qty * unit_price,
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
