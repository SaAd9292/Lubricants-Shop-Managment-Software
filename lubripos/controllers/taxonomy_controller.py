"""Categories & Brands controller: admin-guarded writes."""
from __future__ import annotations

from ..app_context import AppContext
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.taxonomy_service import TaxonomyService

log = get_logger(__name__)


class TaxonomyController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.tax = TaxonomyService(ctx.db, ctx.audit)

    def list(self, table: str, active_only: bool = False) -> list[dict]:
        if table == "categories":
            return self.tax.list_categories(active_only=active_only)
        return self.tax.list_brands(active_only=active_only)

    def add(self, table: str, name: str):
        op = self.tax.add_category if table == "categories" else self.tax.add_brand
        return self._guarded(lambda uid: op(name, user_id=uid))

    def rename(self, table: str, item_id: int, new_name: str):
        return self._guarded(lambda uid: self.tax.rename(table, item_id, new_name, user_id=uid) or item_id)

    def set_active(self, table: str, item_id: int, active: bool):
        return self._guarded(lambda uid: self.tax.set_active(table, item_id, active, user_id=uid) or item_id)

    def delete(self, table: str, item_id: int):
        return self._guarded(lambda uid: self.tax.delete(table, item_id, user_id=uid) or item_id)

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Taxonomy operation failed")
            return False, f"Unexpected error: {exc}", None
