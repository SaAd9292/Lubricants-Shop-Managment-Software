"""User management controller: admin-guarded CRUD + password reset."""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..services.user_service import UserService

log = get_logger(__name__)


class UserController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.users = UserService(ctx.db, ctx.audit)

    def list(self, **kwargs) -> dict[str, Any]:
        return self.users.list_users(**kwargs)

    def get(self, user_id: int) -> dict[str, Any]:
        return self.users.get(user_id)

    def create(self, *, username, password, role, full_name="", must_change_pw=True):
        return self._guarded(lambda uid: self.users.create_user(
            username=username, password=password, role=role, full_name=full_name,
            must_change_pw=must_change_pw, actor_id=uid))

    def update(self, user_id, *, full_name=None, role=None):
        return self._guarded(lambda uid: self.users.update_user(
            user_id, full_name=full_name, role=role, actor_id=uid) or user_id)

    def reset_password(self, user_id, new_password, force_change=True):
        return self._guarded(lambda uid: self.users.reset_password(
            user_id, new_password, force_change=force_change, actor_id=uid) or user_id)

    def set_active(self, user_id, active):
        return self._guarded(lambda uid: self.users.set_active(
            user_id, active, actor_id=uid) or user_id)

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("User operation failed")
            return False, f"Unexpected error: {exc}", None
