"""Cash controller: expected drawer balance + end-of-day physical count.

The count is a verification, open to any signed-in user (it's the cashier's own
drawer). It records what was counted, what the system expected (TODAY'S cash
takings — the single-day drawer figure, not the total business Cash in Hand),
and the difference, and audits it — but never adjusts Cash in Hand, so a real
shortage stays visible for an admin to investigate.
"""
from __future__ import annotations

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.cash_service import CashService

log = get_logger(__name__)


class CashController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.cash = CashService(ctx.db)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(int(minor or 0), sym, mu)

    # -- reads --------------------------------------------------------
    def expected_cash(self, day: str | None = None) -> int:
        """What the drawer should hold for `day` (default today): that DAY'S cash
        takings (its cash in minus cash out), not the total business Cash in
        Hand — the system figure reports use."""
        return self.cash.todays_takings(day)

    def total_cash_in_hand(self) -> int:
        """The system Cash in Hand (running total) — what every report uses."""
        return self.cash.current()

    def last_count(self) -> dict | None:
        return self.cash.last_count()

    # -- write --------------------------------------------------------
    def record_count(self, counted_major: float, *, day: str | None = None,
                     notes: str = ""):
        """counted_major is the physically-counted cash in currency units, for
        `day` (default today). Returns (ok, msg, {count_date, counted_minor,
        expected_minor, difference_minor})."""
        _, mu = self.currency()
        try:
            user = current_session.require_authenticated()
        except LubriPosError as exc:
            return False, str(exc), None
        try:
            counted_minor = money.to_minor(counted_major or 0, mu)
        except (ValueError, ArithmeticError):
            return False, "Enter a valid counted amount.", None
        if counted_minor < 0:
            return False, "Counted cash cannot be negative.", None
        try:
            data = self.cash.record_count(counted_minor, day=day, notes=notes,
                                          user_id=user.id)
            self.ctx.audit.record(
                action="CASH_COUNT", user_id=user.id, entity_type="cash_count",
                entity_id=data["id"],
                details={"counted": data["counted_minor"],
                         "expected": data["expected_minor"],
                         "difference": data["difference_minor"]})
            log.info("Cash count recorded: counted=%s expected=%s diff=%s",
                     data["counted_minor"], data["expected_minor"],
                     data["difference_minor"])
            return True, "ok", data
        except Exception as exc:  # pragma: no cover
            log.exception("Cash count failed")
            return False, f"Unexpected error: {exc}", None
