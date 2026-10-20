"""Money transfers between the cash till and bank/wallet accounts.

A transfer is an INTERNAL move of the shop's own money — it changes where the
money sits, not the total. NULL from/to means the cash till (which is not a row
in payment_accounts). Cash-side transfers flow into CashService's running
balance; account balances are DERIVED here from the ledgers (never a stored
counter), so they self-correct when a transfer is reversed or edited.

Account balance (for a non-cash account `a`), under the shop's single-till model
where supplier payments always come from cash:

    balance(a) = receipts into a         (sales + recoveries tagged to a)
               + transfers into a
               - transfers out of a
               - payouts made from a     (customer_payouts tagged to a)
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)


class TransferService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- writes -------------------------------------------------------
    def create_transfer(self, *, from_account_id: int | None,
                        to_account_id: int | None, amount_minor: int,
                        transfer_date: str | None = None, notes: str | None = None,
                        user_id: int | None = None) -> int:
        """Record a move of `amount_minor` from one place to another, where None
        means the cash till and an int is a payment_accounts id."""
        amount_minor = int(amount_minor)
        if amount_minor <= 0:
            raise ValidationError("Transfer amount must be greater than zero.")
        if from_account_id == to_account_id:
            raise ValidationError("Choose two different places to move between.")
        for acc in (from_account_id, to_account_id):
            if acc is not None and not self.db.query_one(
                    "SELECT id FROM payment_accounts WHERE id = ?", (acc,)):
                raise NotFoundError(f"Account {acc} not found")
        cur = self.db.execute(
            "INSERT INTO money_transfers (from_account_id, to_account_id, "
            "amount_minor, transfer_date, notes, created_by) "
            "VALUES (?,?,?,COALESCE(?, strftime('%Y-%m-%d %H:%M:%S','now')),?,?)",
            (from_account_id, to_account_id, amount_minor, transfer_date,
             (notes or None), user_id))
        tid = cur.lastrowid
        self.audit.record(action="TRANSFER", user_id=user_id,
                          entity_type="money_transfer", entity_id=tid,
                          details={"from": from_account_id, "to": to_account_id,
                                   "amount_minor": amount_minor})
        log.info("Recorded transfer id=%s from=%s to=%s amount=%s",
                 tid, from_account_id, to_account_id, amount_minor)
        return tid

    def reverse_transfer(self, transfer_id: int, *, user_id: int | None = None) -> None:
        """Undo a transfer: delete the row. Cash-in-hand and account balances are
        derived, so both self-correct — nothing to unwind."""
        row = self.db.query_one(
            "SELECT id FROM money_transfers WHERE id = ?", (transfer_id,))
        if not row:
            raise NotFoundError(f"Transfer {transfer_id} not found")
        self.db.execute("DELETE FROM money_transfers WHERE id = ?", (transfer_id,))
        self.audit.record(action="REVERSE_TRANSFER", user_id=user_id,
                          entity_type="money_transfer", entity_id=transfer_id)
        log.warning("Reversed transfer id=%s (deleted)", transfer_id)

    # -- reads --------------------------------------------------------
    def list_transfers(self, *, date_from: str | None = None,
                       date_to: str | None = None) -> dict[str, Any]:
        """Transfer history, newest first, with each side resolved to a name
        ('Cash' for the NULL side)."""
        conds, params = [], []
        if date_from:
            conds.append("substr(t.transfer_date,1,10) >= ?"); params.append(date_from[:10])
        if date_to:
            conds.append("substr(t.transfer_date,1,10) <= ?"); params.append(date_to[:10])
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = [dict(r) for r in self.db.query(
            "SELECT t.id, substr(t.transfer_date,1,16) AS date, t.amount_minor AS amount, "
            "COALESCE(af.name,'Cash') AS from_name, COALESCE(at.name,'Cash') AS to_name, "
            "COALESCE(t.notes,'') AS notes "
            "FROM money_transfers t "
            "LEFT JOIN payment_accounts af ON af.id = t.from_account_id "
            "LEFT JOIN payment_accounts at ON at.id = t.to_account_id "
            f"{where} ORDER BY t.transfer_date DESC, t.id DESC", tuple(params))]
        return {"rows": rows, "total": sum(r["amount"] for r in rows)}

    def account_balances(self) -> list[dict[str, Any]]:
        """Each active bank/wallet account with its DERIVED balance (see module
        docstring). Correlated subqueries keep it one readable query; everything
        is computed, nothing stored."""
        return [dict(r) for r in self.db.query(
            """
            SELECT a.id, a.method, a.name,
              COALESCE((SELECT SUM(grand_total_minor) FROM sales
                        WHERE payment_account_id = a.id AND status='completed'), 0)
            + COALESCE((SELECT SUM(amount_minor) FROM customer_payments
                        WHERE account_id = a.id), 0)
            + COALESCE((SELECT SUM(amount_minor) FROM money_transfers
                        WHERE to_account_id = a.id), 0)
            - COALESCE((SELECT SUM(amount_minor) FROM money_transfers
                        WHERE from_account_id = a.id), 0)
            - COALESCE((SELECT SUM(amount_minor) FROM customer_payouts
                        WHERE account_id = a.id), 0)
              AS balance
            FROM payment_accounts a
            WHERE a.is_active = 1
            ORDER BY a.method, a.name
            """)]

    def active_accounts(self) -> list[dict[str, Any]]:
        """Lightweight list for the From/To pickers: id, method, name."""
        return [dict(r) for r in self.db.query(
            "SELECT id, method, name FROM payment_accounts WHERE is_active = 1 "
            "ORDER BY method, name")]
