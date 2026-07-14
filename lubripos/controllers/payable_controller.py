"""Payable controller: supplier balances + recording payments.

Reads are open to anyone who can see the Payables screen. Recording a payment
moves money and is admin-only.
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.payable_service import PayableService

log = get_logger(__name__)


class PayableController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.payables = PayableService(ctx.db, ctx.audit)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    # -- reads --------------------------------------------------------
    def list(self, **kwargs) -> dict[str, Any]:
        return self.payables.list_payables(**kwargs)

    def ledger(self, supplier_id: int) -> dict[str, Any]:
        return self.payables.supplier_ledger(supplier_id)

    def total_outstanding(self) -> int:
        return self.payables.total_outstanding()

    # -- writes -------------------------------------------------------
    def record_payment(self, supplier_id: int, amount: float, *,
                       method: str | None = None, notes: str | None = None,
                       payment_date: str | None = None):
        """amount is a decimal in the shop currency. Returns (ok, msg, payment_id)."""
        _, mu = self.currency()
        try:
            amount_minor = money.to_minor(amount or 0, mu)
        except (ValueError, ArithmeticError):
            return False, "Invalid payment amount.", None
        try:
            user = current_session.require_role("admin")
            pid = self.payables.record_payment(
                supplier_id, amount_minor, method=method, notes=notes,
                payment_date=payment_date, user_id=user.id)
            return True, "ok", pid
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Record payment failed")
            return False, f"Unexpected error: {exc}", None
