"""Payment accounts: named Bank / EasyPaisa / JazzCash destinations.

A shop often holds several mobile-wallet or bank accounts; recording which one
received the money lets the day close reconcile per account. Cash is single and
is NOT modelled here. Accounts can be deactivated (hidden from the POS) or
deleted outright — sales snapshot the account name, so history is unaffected.
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger

log = get_logger(__name__)

METHODS = ("Bank", "EasyPaisa", "JazzCash")


class _NullAudit:
    def record(self, **_: Any) -> None:  # pragma: no cover - test fallback
        pass


class PaymentAccountService:
    def __init__(self, db, audit=None) -> None:
        self.db = db
        self.audit = audit or _NullAudit()

    # -- read ---------------------------------------------------------
    def list_accounts(self, *, method: str | None = None,
                      active_only: bool = False) -> list[dict[str, Any]]:
        clauses, params = [], []
        if method:
            clauses.append("method = ?")
            params.append(method)
        if active_only:
            clauses.append("is_active = 1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return [dict(r) for r in self.db.query(
            f"SELECT * FROM payment_accounts {where} "
            f"ORDER BY method, name COLLATE NOCASE", tuple(params))]

    def get(self, account_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM payment_accounts WHERE id = ?", (account_id,))
        if not row:
            raise NotFoundError("Payment account not found.")
        return dict(row)

    # -- validation ---------------------------------------------------
    def _clean(self, data: dict[str, Any]) -> tuple[str, str, str]:
        method = (data.get("method") or "").strip()
        if method not in METHODS:
            raise ValidationError(f"Method must be one of: {', '.join(METHODS)}.")
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Account name is required.")
        account_no = (data.get("account_no") or "").strip()
        return method, name, account_no

    # -- write --------------------------------------------------------
    def create(self, data: dict[str, Any], *, user_id: int | None = None) -> int:
        method, name, account_no = self._clean(data)
        cur = self.db.execute(
            "INSERT INTO payment_accounts (method, name, account_no) VALUES (?,?,?)",
            (method, name, account_no or None))
        acc_id = cur.lastrowid
        self.audit.record(action="CREATE", user_id=user_id,
                          entity_type="payment_account", entity_id=acc_id,
                          details={"method": method, "name": name})
        log.info("Created payment account id=%s %s/%s", acc_id, method, name)
        return acc_id

    def update(self, account_id: int, data: dict[str, Any], *,
               user_id: int | None = None) -> None:
        self.get(account_id)
        method, name, account_no = self._clean(data)
        self.db.execute(
            "UPDATE payment_accounts SET method=?, name=?, account_no=? WHERE id=?",
            (method, name, account_no or None, account_id))
        self.audit.record(action="UPDATE", user_id=user_id,
                          entity_type="payment_account", entity_id=account_id,
                          details={"method": method, "name": name})

    def set_active(self, account_id: int, active: bool, *,
                   user_id: int | None = None) -> None:
        self.get(account_id)
        self.db.execute("UPDATE payment_accounts SET is_active=? WHERE id=?",
                        (1 if active else 0, account_id))
        self.audit.record(action="UPDATE", user_id=user_id,
                          entity_type="payment_account", entity_id=account_id,
                          details={"is_active": bool(active)})

    def delete(self, account_id: int, *, user_id: int | None = None) -> None:
        acc = self.get(account_id)
        # Safe: sales.payment_account_id is ON DELETE SET NULL and the account
        # name is snapshotted on each sale, so history stays intact.
        self.db.execute("DELETE FROM payment_accounts WHERE id=?", (account_id,))
        self.audit.record(action="DELETE", user_id=user_id,
                          entity_type="payment_account", entity_id=account_id,
                          details={"name": acc["name"]})
        log.info("Deleted payment account id=%s (%s)", account_id, acc["name"])
