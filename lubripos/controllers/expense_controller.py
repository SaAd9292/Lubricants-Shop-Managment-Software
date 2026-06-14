"""Expense controller: admin-guarded writes, decimal->minor conversion."""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.expense_service import ExpenseService

log = get_logger(__name__)


class ExpenseController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.expenses = ExpenseService(ctx.db, ctx.audit)

    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    # reads
    def list(self, **kwargs) -> dict[str, Any]:
        return self.expenses.list_expenses(**kwargs)

    def get(self, expense_id: int) -> dict[str, Any]:
        return self.expenses.get(expense_id)

    def categories(self) -> list[dict]:
        return self.expenses.list_categories()

    def add_category(self, name: str):
        return self._guarded(lambda uid: self.expenses.add_category(name, user_id=uid))

    # writes
    def save(self, form: dict[str, Any], expense_id: int | None = None):
        _, mu = self.currency()
        data = dict(form)
        try:
            if "amount" in data:
                data["amount_minor"] = money.to_minor(data.pop("amount"), mu)
        except (ValueError, ArithmeticError):
            return False, "Amount must be a valid number.", None

        def op(uid):
            if expense_id is None:
                return self.expenses.create(data, user_id=uid)
            self.expenses.update(expense_id, data, user_id=uid)
            return expense_id
        return self._guarded(op)

    def delete(self, expense_id: int):
        return self._guarded(
            lambda uid: self.expenses.delete(expense_id, user_id=uid) or expense_id
        )

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Expense operation failed")
            return False, f"Unexpected error: {exc}", None
