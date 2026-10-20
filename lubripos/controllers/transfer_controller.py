"""Transfer controller: moving the shop's own money between the cash till and a
bank/wallet account (e.g. sweeping the day's JazzCash collections into cash).

Reads (balances, history, account pickers) are open to anyone who can open the
Cash Recovery screen. Writes move money, so — like supplier payments — they are
admin-only. Every write returns the uniform (ok, msg, data) tuple the views
expect, so the UI never has to catch service exceptions itself.
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.transfer_service import TransferService

log = get_logger(__name__)


class TransferController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.transfers = TransferService(ctx.db, ctx.audit)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    # -- reads --------------------------------------------------------
    def active_accounts(self) -> list[dict[str, Any]]:
        """Bank/wallet accounts for the From/To pickers (cash is added by the view
        as the NULL option, since the till is not a payment_accounts row)."""
        return self.transfers.active_accounts()

    def account_balances(self) -> list[dict[str, Any]]:
        """Each account's DERIVED balance, for display alongside the form."""
        return self.transfers.account_balances()

    def history(self, *, date_from: str | None = None,
                date_to: str | None = None) -> dict[str, Any]:
        return self.transfers.list_transfers(date_from=date_from, date_to=date_to)

    # -- writes -------------------------------------------------------
    def create(self, *, from_account_id: int | None, to_account_id: int | None,
               amount: float, transfer_date: str | None = None,
               notes: str | None = None):
        """amount is a decimal in the shop currency; account ids are payment_accounts
        ids, or None for the cash till. Returns (ok, msg, transfer_id)."""
        _, mu = self.currency()
        try:
            amount_minor = money.to_minor(amount or 0, mu)
        except (ValueError, ArithmeticError):
            return False, "Invalid transfer amount.", None
        try:
            user = current_session.require_permission("money.transfer")
            tid = self.transfers.create_transfer(
                from_account_id=from_account_id, to_account_id=to_account_id,
                amount_minor=amount_minor, transfer_date=transfer_date,
                notes=notes, user_id=user.id)
            return True, "ok", tid
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Record transfer failed")
            return False, f"Unexpected error: {exc}", None

    def reverse(self, transfer_id: int):
        """Undo a transfer (needs the Delete/reverse privilege). (ok, msg, data)."""
        try:
            user = current_session.require_permission("record.delete")
            self.transfers.reverse_transfer(transfer_id, user_id=user.id)
            return True, "ok", None
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Reverse transfer failed")
            return False, f"Unexpected error: {exc}", None
