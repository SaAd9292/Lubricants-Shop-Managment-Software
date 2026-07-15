"""Customer controller: directory + purchase history.

Viewing and managing customers requires the grantable "customers" screen
privilege (admins always have it). Permanent delete is admin-only.
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core import money
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.customer_service import CustomerService

log = get_logger(__name__)


class CustomerController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.customers = CustomerService(ctx.db, ctx.audit)

    # -- currency -----------------------------------------------------
    def currency(self) -> tuple[str, int]:
        c = self.ctx.company.get_company()
        return c.get("currency_symbol", "Rs"), c.get("currency_minor_units", 100)

    def fmt(self, minor: int) -> str:
        sym, mu = self.currency()
        return money.format_money(minor, sym, mu)

    # -- reads --------------------------------------------------------
    def list(self, **kwargs) -> dict[str, Any]:
        return self.customers.list_customers(**kwargs)

    def get(self, customer_id: int) -> dict[str, Any]:
        return self.customers.get(customer_id)

    def history(self, customer_id: int) -> dict[str, Any]:
        return self.customers.history(customer_id)

    # -- writes -------------------------------------------------------
    def save(self, form: dict[str, Any], customer_id: int | None = None):
        def op(uid):
            if customer_id is None:
                return self.customers.find_or_create(
                    form.get("name", ""), form.get("phone"), user_id=uid)
            self.customers.update(customer_id, form, user_id=uid)
            return customer_id
        return self._guarded(op)

    def remove(self, customer_id: int):
        return self._guarded(
            lambda uid: self.customers.set_active(customer_id, False, user_id=uid)
            or customer_id)

    def reactivate(self, customer_id: int):
        return self._guarded(
            lambda uid: self.customers.set_active(customer_id, True, user_id=uid)
            or customer_id)

    def hard_delete(self, customer_id: int):
        try:
            user = current_session.require_role("admin")
            self.customers.delete(customer_id, user_id=user.id)
            return True, "ok", customer_id
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Customer delete failed")
            return False, f"Unexpected error: {exc}", None

    def _guarded(self, op):
        try:
            user = current_session.require_permission("customers")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Customer operation failed")
            return False, f"Unexpected error: {exc}", None
