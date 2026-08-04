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

    def balance_owed(self, customer_id: int) -> int:
        return self.customers.balance_owed(customer_id)

    def ledger(self, customer_id: int) -> dict[str, Any]:
        return self.customers.debt_ledger(customer_id)

    def record_payment(self, customer_id: int, amount_major: float, *,
                       method: str | None = None, account_id: int | None = None,
                       account_name: str | None = None, notes: str | None = None):
        """amount_major is in currency units (e.g. rupees); converted to minor.
        Returns (ok, msg, payment_id) so the caller can print a receipt."""
        def op(uid):
            _, mu = self.currency()
            return self.customers.record_payment(
                customer_id, money.to_minor(amount_major or 0, mu),
                method=method, account_id=account_id, account_name=account_name,
                notes=notes, user_id=uid)
        return self._guarded(op)

    def payment_receipt(self, payment_id: int, dest: str | None = None):
        """Build a printable PDF receipt for a repayment. If dest is None a temp
        file is used (the caller opens it for print/hand-off)."""
        import os
        import tempfile
        from ..reports.payment_receipt_pdf import generate_payment_receipt_pdf
        try:
            pay = self.customers.get_payment(payment_id)
            company = self.ctx.company.get_company()
            if dest is None:
                dest = os.path.join(tempfile.gettempdir(),
                                    f"payment_PMT-{payment_id:05d}.pdf")
            path = generate_payment_receipt_pdf(payment=pay, company=company,
                                                output_path=dest)
            return True, "ok", path
        except Exception as exc:  # pragma: no cover
            log.exception("Payment receipt failed")
            return False, str(exc), None

    # -- writes -------------------------------------------------------
    def save(self, form: dict[str, Any], customer_id: int | None = None):
        # convert the opening-balance field (entered in rupees) to minor units
        if "opening_debt" in form:
            _, mu = self.currency()
            form = dict(form)
            form["opening_debt_minor"] = money.to_minor(form.pop("opening_debt") or 0, mu)
        def op(uid):
            if customer_id is None:
                return self.customers.create(form, user_id=uid)
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
