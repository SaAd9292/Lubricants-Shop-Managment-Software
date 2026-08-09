"""Cash drawer (till) sessions.

A till is OPENED with a starting float, takes cash in (cash sales + cash debt
repayments) and out (refunds, plus logged pay-outs like chai or a bank deposit),
then is CLOSED with a physical cash count. At close we snapshot the numbers and
record the variance (counted - expected) so an owner can spot till shortages.

    expected cash = opening float
                  + cash sales + cash repayments + cash paid-IN
                  - cash refunds - cash paid-OUT
    variance      = counted cash - expected cash
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)


class CashDrawerService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- open / current ----------------------------------------------
    def current(self) -> dict[str, Any] | None:
        """The currently OPEN session, or None."""
        row = self.db.query_one(
            "SELECT * FROM cash_sessions WHERE status='open' ORDER BY id DESC LIMIT 1")
        return dict(row) if row else None

    def open_session(self, opening_float_minor: int, *, user_id: int | None = None) -> int:
        opening_float_minor = int(opening_float_minor or 0)
        if opening_float_minor < 0:
            raise ValidationError("Opening float cannot be negative.")
        if self.current():
            raise ValidationError("A cash drawer is already open. Close it first.")
        cur = self.db.execute(
            "INSERT INTO cash_sessions (opening_float_minor, opened_by) VALUES (?, ?)",
            (opening_float_minor, user_id))
        sid = cur.lastrowid
        self.audit.record(action="CASH_OPEN", user_id=user_id, entity_type="cash_session",
                          entity_id=sid, details={"float": opening_float_minor})
        log.info("Cash drawer opened id=%s float=%s", sid, opening_float_minor)
        return sid

    def get(self, session_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM cash_sessions WHERE id = ?", (session_id,))
        if not row:
            raise NotFoundError(f"Cash session {session_id} not found")
        return dict(row)

    # -- movements ----------------------------------------------------
    def add_movement(self, session_id: int, kind: str, amount_minor: int, *,
                     reason: str | None = None, user_id: int | None = None) -> int:
        """Log cash taken OUT ('out') of or put IN ('in') to the open drawer."""
        session = self.get(session_id)
        if session["status"] != "open":
            raise ValidationError("This drawer is already closed.")
        if kind not in ("out", "in"):
            raise ValidationError("Movement kind must be 'out' or 'in'.")
        amount_minor = int(amount_minor)
        if amount_minor <= 0:
            raise ValidationError("Amount must be greater than zero.")
        cur = self.db.execute(
            "INSERT INTO cash_movements (session_id, kind, amount_minor, reason, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, kind, amount_minor, (reason or "").strip() or None, user_id))
        mid = cur.lastrowid
        self.audit.record(action="CASH_" + kind.upper(), user_id=user_id,
                          entity_type="cash_movement", entity_id=mid,
                          details={"session": session_id, "amount": amount_minor,
                                   "reason": reason})
        log.info("Cash %s id=%s session=%s amount=%s", kind, mid, session_id, amount_minor)
        return mid

    def movements(self, session_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT id, kind, amount_minor, COALESCE(reason,'') AS reason, "
            "substr(created_at,1,16) AS at FROM cash_movements "
            "WHERE session_id = ? ORDER BY id", (session_id,))]

    # -- live totals + expected cash ----------------------------------
    def _sum(self, sql: str, params: tuple) -> int:
        row = self.db.query_one(sql, params)
        return int((row["v"] if row else 0) or 0)

    def totals(self, session: dict[str, Any], *, until: str | None = None) -> dict[str, int]:
        """Cash-in / cash-out for a session between its open time and `until`
        (defaults to now). Used both for the live view and the close snapshot."""
        start = session["opened_at"]
        end = until or "9999-12-31 23:59:59"
        sid = session["id"]
        cash_sales = self._sum(
            "SELECT COALESCE(SUM(grand_total_minor),0) v FROM sales "
            "WHERE status='completed' AND payment_method='Cash' "
            "AND sale_date >= ? AND sale_date <= ?", (start, end))
        cash_repay = self._sum(
            "SELECT COALESCE(SUM(amount_minor),0) v FROM customer_payments "
            "WHERE (method='Cash' OR method IS NULL) "
            "AND payment_date >= ? AND payment_date <= ?", (start, end))
        cash_refunds = self._sum(
            "SELECT COALESCE(SUM(sri.line_total_minor),0) v "
            "FROM sale_return_items sri JOIN sale_returns sr ON sr.id = sri.return_id "
            "WHERE sr.return_date >= ? AND sr.return_date <= ?", (start, end))
        # Match expenses by when they were RECORDED (created_at), not the chosen
        # accounting date: the expense-entry form stamps expense_date at midnight,
        # which would fall before a drawer opened later the same day.
        cash_expenses = self._sum(
            "SELECT COALESCE(SUM(amount_minor),0) v FROM expenses "
            "WHERE payment_method='Cash' AND created_at >= ? AND created_at <= ?",
            (start, end))
        paid_out = self._sum(
            "SELECT COALESCE(SUM(amount_minor),0) v FROM cash_movements "
            "WHERE session_id = ? AND kind='out'", (sid,))
        paid_in = self._sum(
            "SELECT COALESCE(SUM(amount_minor),0) v FROM cash_movements "
            "WHERE session_id = ? AND kind='in'", (sid,))
        opening = int(session["opening_float_minor"] or 0)
        expected = (opening + cash_sales + cash_repay + paid_in
                    - cash_refunds - cash_expenses - paid_out)
        return {"opening": opening, "cash_sales": cash_sales, "cash_repay": cash_repay,
                "cash_refunds": cash_refunds, "cash_expenses": cash_expenses,
                "paid_out": paid_out, "paid_in": paid_in, "expected": expected}

    # -- close --------------------------------------------------------
    def close_session(self, session_id: int, counted_cash_minor: int, *,
                      note: str | None = None, user_id: int | None = None) -> dict[str, Any]:
        session = self.get(session_id)
        if session["status"] != "open":
            raise ValidationError("This drawer is already closed.")
        counted_cash_minor = int(counted_cash_minor or 0)
        if counted_cash_minor < 0:
            raise ValidationError("Counted cash cannot be negative.")
        now = self.db.query_one("SELECT strftime('%Y-%m-%d %H:%M:%S','now') AS t")["t"]
        t = self.totals(session, until=now)
        variance = counted_cash_minor - t["expected"]
        self.db.execute(
            "UPDATE cash_sessions SET status='closed', closed_at=?, closed_by=?, "
            "counted_cash_minor=?, expected_cash_minor=?, variance_minor=?, "
            "cash_sales_minor=?, cash_repay_minor=?, cash_refunds_minor=?, "
            "cash_expenses_minor=?, paid_out_minor=?, paid_in_minor=?, note=? WHERE id=?",
            (now, user_id, counted_cash_minor, t["expected"], variance,
             t["cash_sales"], t["cash_repay"], t["cash_refunds"], t["cash_expenses"],
             t["paid_out"], t["paid_in"], (note or "").strip() or None, session_id))
        self.audit.record(action="CASH_CLOSE", user_id=user_id, entity_type="cash_session",
                          entity_id=session_id,
                          details={"counted": counted_cash_minor,
                                   "expected": t["expected"], "variance": variance})
        log.info("Cash drawer closed id=%s counted=%s expected=%s variance=%s",
                 session_id, counted_cash_minor, t["expected"], variance)
        return self.get(session_id)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT cs.*, ou.username AS opened_by_name, cu.username AS closed_by_name "
            "FROM cash_sessions cs "
            "LEFT JOIN users ou ON ou.id = cs.opened_by "
            "LEFT JOIN users cu ON cu.id = cs.closed_by "
            "ORDER BY cs.id DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in rows]
