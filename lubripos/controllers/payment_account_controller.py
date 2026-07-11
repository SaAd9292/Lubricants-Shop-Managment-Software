"""Payment account controller: admin-guarded CRUD for named payment accounts.

Reads (list) are open so the POS can populate the cashier's account dropdown;
writes require the admin role.
"""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.payment_account_service import METHODS, PaymentAccountService

log = get_logger(__name__)


class PaymentAccountController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.accounts = PaymentAccountService(ctx.db, ctx.audit)

    def methods(self) -> list[str]:
        return list(METHODS)

    def list(self, **kwargs) -> list[dict[str, Any]]:
        return self.accounts.list_accounts(**kwargs)

    def create(self, data):
        return self._guarded(lambda uid: self.accounts.create(data, user_id=uid))

    def update(self, account_id, data):
        return self._guarded(
            lambda uid: self.accounts.update(account_id, data, user_id=uid) or account_id)

    def set_active(self, account_id, active):
        return self._guarded(
            lambda uid: self.accounts.set_active(account_id, active, user_id=uid) or account_id)

    def delete(self, account_id):
        return self._guarded(
            lambda uid: self.accounts.delete(account_id, user_id=uid) or account_id)

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Payment account operation failed")
            return False, f"Unexpected error: {exc}", None
