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
            balance = r["purchased"] - paid
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
            "SELECT id, name, phone FROM suppliers WHERE id = ?", (supplier_id,))
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
        return {"supplier": dict(sup), "purchases": purchases, "payments": payments,
                "purchased": purchased, "paid": paid, "balance": purchased - paid}

    # -- writes -------------------------------------------------------
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
