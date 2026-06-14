"""Supplier controller: admin-guarded writes, maps errors for the UI."""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.supplier_service import SupplierService

log = get_logger(__name__)


class SupplierController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.suppliers = SupplierService(ctx.db, ctx.audit)

    # reads
    def list(self, **kwargs) -> dict[str, Any]:
        return self.suppliers.list_suppliers(**kwargs)

    def get(self, supplier_id: int) -> dict[str, Any]:
        return self.suppliers.get(supplier_id)

    # writes
    def save(self, form: dict[str, Any], supplier_id: int | None = None):
        def op(uid):
            if supplier_id is None:
                return self.suppliers.create(form, user_id=uid)
            self.suppliers.update(supplier_id, form, user_id=uid)
            return supplier_id
        return self._guarded(op)

    def delete(self, supplier_id: int):
        return self._guarded(
            lambda uid: self.suppliers.set_active(supplier_id, False, user_id=uid) or supplier_id
        )

    def reactivate(self, supplier_id: int):
        return self._guarded(
            lambda uid: self.suppliers.set_active(supplier_id, True, user_id=uid) or supplier_id
        )

    def hard_delete(self, supplier_id: int):
        return self._guarded(
            lambda uid: self.suppliers.delete(supplier_id, user_id=uid) or supplier_id)

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Supplier operation failed")
            return False, f"Unexpected error: {exc}", None
