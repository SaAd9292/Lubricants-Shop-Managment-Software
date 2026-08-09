"""Cash drawer controller: open/close the till + log cash movements.

Writes require the grantable "cashdrawer" screen privilege (admins always have
it). Amounts come in as currency units and are converted to integer minor units.
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.cash_drawer_service import CashDrawerService

log = get_logger(__name__)


class CashDrawerController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.cash = CashDrawerService(ctx.db, ctx.audit)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(int(minor or 0), sym, mu)

    # -- reads (the screen is already permission-gated) ---------------
    def current(self) -> dict[str, Any] | None:
        return self.cash.current()

    def totals(self, session: dict[str, Any]) -> dict[str, int]:
        return self.cash.totals(session)

    def movements(self, session_id: int) -> list[dict[str, Any]]:
        return self.cash.movements(session_id)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.cash.list_sessions(limit)

    # -- writes -------------------------------------------------------
    def open(self, opening_float_major: float):
        _, mu = self.currency()
        return self._guarded(lambda uid: self.cash.open_session(
            money.to_minor(opening_float_major or 0, mu), user_id=uid))

    def add_movement(self, session_id: int, kind: str, amount_major: float,
                     reason: str | None = None):
        _, mu = self.currency()
        return self._guarded(lambda uid: self.cash.add_movement(
            session_id, kind, money.to_minor(amount_major or 0, mu),
            reason=reason, user_id=uid))

    def close(self, session_id: int, counted_major: float, note: str | None = None):
        _, mu = self.currency()
        return self._guarded(lambda uid: self.cash.close_session(
            session_id, money.to_minor(counted_major or 0, mu),
            note=note, user_id=uid))

    def _guarded(self, op):
        try:
            user = current_session.require_permission("cashdrawer")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Cash drawer operation failed")
            return False, f"Unexpected error: {exc}", None
