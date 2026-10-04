"""Supplier payables: what the shop owes each supplier, and the payments that
settle it.

Money model (all INTEGER minor units):
  * Every purchase is a liability of `purchases.total_minor`.
  * `purchases.amount_paid_minor` is what was paid AT purchase time.
  * `supplier_payments` records payments made LATER.
  * balance(supplier) = SUM(total_minor - amount_paid_minor) - SUM(payments)

Payables are intentionally NOT part of the P&L reports: buying stock is not an
expense (it becomes COGS when the item sells) and paying a supplier is a cash
movement, not a cost. This module is the standalone payables ledger.
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)


class PayableService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- reads --------------------------------------------------------
    def list_payables(self, *, only_outstanding: bool = False,
                      search: str = "") -> dict[str, Any]:
        """One row per active supplier with purchased / paid / balance totals.
        Sorted by balance owed (largest first)."""
        clauses = ["s.is_active = 1"]
        params: list[Any] = []
        if search:
            clauses.append("s.name LIKE ?")
            params.append(f"%{search.strip()}%")
        where = "WHERE " + " AND ".join(clauses)
        rows = self.db.query(
            f"""
            SELECT s.id, s.name, s.phone,
                   COALESCE(s.opening_debt_minor, 0) AS opening,
                   COALESCE(pu.purchased, 0)  AS purchased,
                   COALESCE(pu.paid_at, 0)    AS paid_at_purchase,
                   COALESCE(pm.paid_later, 0) AS paid_later
            FROM suppliers s
            LEFT JOIN (SELECT supplier_id,
                              SUM(total_minor)       AS purchased,
                              SUM(amount_paid_minor) AS paid_at
                       FROM purchases WHERE supplier_id IS NOT NULL
                       GROUP BY supplier_id) pu ON pu.supplier_id = s.id
            LEFT JOIN (SELECT supplier_id, SUM(amount_minor) AS paid_later
                       FROM supplier_payments GROUP BY supplier_id) pm
                   ON pm.supplier_id = s.id
            {where}
            ORDER BY s.name COLLATE NOCASE
            """,
            tuple(params),
        )
        out = []
        for r in rows:
            r = dict(r)
            paid = r["paid_at_purchase"] + r["paid_later"]
            balance = r["opening"] + r["purchased"] - paid
            if only_outstanding and balance <= 0:
                continue
            out.append({"id": r["id"], "name": r["name"], "phone": r["phone"],
                        "purchased": r["purchased"], "paid": paid,
                        "balance": balance})
        out.sort(key=lambda x: x["balance"], reverse=True)
        total_balance = sum(x["balance"] for x in out)
        return {"rows": out, "total_balance": total_balance}

    def total_outstanding(self) -> int:
        """Sum of positive balances across all suppliers (for the dashboard)."""
        return sum(max(0, r["balance"])
                   for r in self.list_payables()["rows"])

    def supplier_ledger(self, supplier_id: int) -> dict[str, Any]:
        """Full history for one supplier: its purchases and its payments,
        with running totals."""
        sup = self.db.query_one(
            "SELECT id, name, phone, COALESCE(opening_debt_minor,0) AS opening "
            "FROM suppliers WHERE id = ?", (supplier_id,))
        if not sup:
            raise NotFoundError(f"Supplier {supplier_id} not found")
        purchases = [dict(r) for r in self.db.query(
            """SELECT id, substr(purchase_date,1,10) AS date,
                  COALESCE(supplier_invoice_no,'') AS invoice,
                  total_minor AS total, amount_paid_minor AS paid_at,
                  (total_minor - amount_paid_minor) AS credit
               FROM purchases WHERE supplier_id = ?
               ORDER BY purchase_date DESC, id DESC""", (supplier_id,))]
        payments = [dict(r) for r in self.db.query(
            """SELECT id, substr(payment_date,1,10) AS date, amount_minor AS amount,
                  COALESCE(method,'') AS method, COALESCE(notes,'') AS notes
               FROM supplier_payments WHERE supplier_id = ?
               ORDER BY payment_date DESC, id DESC""", (supplier_id,))]
        purchased = sum(p["total"] for p in purchases)
        paid = sum(p["paid_at"] for p in purchases) + sum(p["amount"] for p in payments)
        opening = sup["opening"]
        return {"supplier": dict(sup), "purchases": purchases, "payments": payments,
                "purchased": purchased, "paid": paid, "opening": opening,
                "balance": opening + purchased - paid}

    def list_payments(self, *, date_from: str | None = None,
                      date_to: str | None = None) -> dict[str, Any]:
        """Every payment made to suppliers, newest first, optionally within a
        date range (inclusive, by date part). Returns {rows, total}."""
        conds, params = [], []
        if date_from:
            conds.append("substr(sp.payment_date,1,10) >= ?"); params.append(date_from[:10])
        if date_to:
            conds.append("substr(sp.payment_date,1,10) <= ?"); params.append(date_to[:10])
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = [dict(r) for r in self.db.query(
            "SELECT sp.id AS id, sp.payment_date AS payment_date_full, "
            "substr(sp.payment_date,1,16) AS date, "
            "COALESCE(s.name,'(removed)') AS supplier, sp.supplier_id AS supplier_id, "
            "sp.amount_minor AS amount, "
            "COALESCE(sp.method,'Cash') AS method, COALESCE(sp.notes,'') AS notes "
            "FROM supplier_payments sp LEFT JOIN suppliers s ON s.id = sp.supplier_id "
            f"{where} ORDER BY sp.payment_date DESC, sp.id DESC", tuple(params))]
        total = sum(r["amount"] for r in rows)
        return {"rows": rows, "total": total}

    def payments_min_date(self) -> str | None:
        """Earliest supplier-payment date (YYYY-MM-DD), for a sensible default
        'from' on the payments list; None if there are no payments yet."""
        row = self.db.query_one(
            "SELECT substr(MIN(payment_date),1,10) AS d FROM supplier_payments")
        return row["d"] if row and row["d"] else None

    # -- writes -------------------------------------------------------
    def get_payment(self, payment_id: int) -> dict[str, Any]:
        """One supplier payment's editable fields (no account columns, so this
        works on older DBs that predate them)."""
        row = self.db.query_one(
            "SELECT sp.id, sp.supplier_id, COALESCE(s.name,'(removed)') AS supplier_name, "
            "sp.amount_minor, COALESCE(sp.method,'Cash') AS method, "
            "COALESCE(sp.notes,'') AS notes, sp.payment_date "
            "FROM supplier_payments sp LEFT JOIN suppliers s ON s.id = sp.supplier_id "
            "WHERE sp.id = ?", (payment_id,))
        if not row:
            raise NotFoundError(f"Payment {payment_id} not found")
        return dict(row)

    def reverse_payment(self, payment_id: int, *, user_id: int | None = None) -> dict[str, Any]:
        """Undo a payment made to a supplier: delete the row. The supplier's
        payable and Cash-in-Hand both self-correct (derived from this ledger).
        Audited."""
        row = self.db.query_one(
            "SELECT supplier_id, amount_minor FROM supplier_payments WHERE id = ?",
            (payment_id,))
        if not row:
            raise NotFoundError(f"Payment {payment_id} not found")
        self.db.execute("DELETE FROM supplier_payments WHERE id = ?", (payment_id,))
        self.audit.record(action="REVERSE_PAYMENT", user_id=user_id,
                          entity_type="supplier", entity_id=row["supplier_id"],
                          details={"payment_id": payment_id,
                                   "amount_minor": row["amount_minor"]})
        log.warning("Supplier payment id=%s reversed (deleted); payable restored",
                    payment_id)
        return {"payment_id": payment_id, "amount_minor": row["amount_minor"],
                "supplier_id": row["supplier_id"]}

    def update_payment(self, payment_id: int, *, supplier_id: int | None = None,
                       amount_minor: int | None = None, method: str | None = None,
                       notes: str | None = None, payment_date: str | None = None,
                       user_id: int | None = None) -> dict[str, Any]:
        """Correct a supplier payment in place (supplier, amount, method, date,
        note). Any field left None is unchanged. Safe because the payable and
        cash are derived. Account columns are intentionally not touched so this
        works on older DBs."""
        row = self.db.query_one(
            "SELECT id, supplier_id, amount_minor, method, notes, payment_date "
            "FROM supplier_payments WHERE id = ?", (payment_id,))
        if not row:
            raise NotFoundError(f"Payment {payment_id} not found")
        new_sup = row["supplier_id"] if supplier_id is None else int(supplier_id)
        if not self.db.query_one("SELECT id FROM suppliers WHERE id = ?", (new_sup,)):
            raise NotFoundError(f"Supplier {new_sup} not found")
        amt = row["amount_minor"] if amount_minor is None else int(amount_minor)
        if amt <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        new_method = row["method"] if method is None else ((method or "").strip() or None)
        new_notes = row["notes"] if notes is None else ((notes or "").strip() or None)
        if payment_date is None:
            new_date = row["payment_date"]
        else:
            pd = payment_date.strip()
            new_date = f"{pd} 12:00:00" if len(pd) == 10 else pd
        self.db.execute(
            "UPDATE supplier_payments SET supplier_id=?, amount_minor=?, method=?, "
            "notes=?, payment_date=? WHERE id=?",
            (new_sup, amt, new_method, new_notes, new_date, payment_id))
        self.audit.record(action="EDIT_PAYMENT", user_id=user_id,
                          entity_type="supplier", entity_id=new_sup,
                          details={"payment_id": payment_id, "amount_minor": amt,
                                   "method": new_method})
        log.info("Edited supplier payment id=%s (supplier=%s, amount=%s, method=%s)",
                 payment_id, new_sup, amt, new_method)
        return {"payment_id": payment_id, "supplier_id": new_sup}

    def record_payment(self, supplier_id: int, amount_minor: int, *,
                       method: str | None = None, notes: str | None = None,
                       payment_date: str | None = None,
                       purchase_id: int | None = None,
                       user_id: int | None = None) -> int:
        """Record a payment made to a supplier. amount must be positive."""
        sup = self.db.query_one(
            "SELECT id FROM suppliers WHERE id = ?", (supplier_id,))
        if not sup:
            raise NotFoundError(f"Supplier {supplier_id} not found")
        amount_minor = int(amount_minor)
        if amount_minor <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        cur = self.db.execute(
            "INSERT INTO supplier_payments (supplier_id, purchase_id, amount_minor, "
            "method, notes, payment_date) "
            "VALUES (?,?,?,?,?,COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')))",
            (supplier_id, purchase_id, amount_minor,
             (method or None), (notes or None), payment_date),
        )
        pay_id = cur.lastrowid
        self.audit.record(action="PAYMENT", user_id=user_id, entity_type="supplier",
                          entity_id=supplier_id,
                          details={"payment_id": pay_id, "amount_minor": amount_minor,
                                   "method": method})
        log.info("Recorded supplier payment id=%s supplier=%s amount=%s",
                 pay_id, supplier_id, amount_minor)
        return pay_id
