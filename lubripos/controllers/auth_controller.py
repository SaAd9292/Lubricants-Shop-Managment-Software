"""Controller for login and session lifecycle."""
from __future__ import annotations

from ..app_context import AppContext
from ..core.exceptions import AuthError
from ..core.session import current_session


class AuthController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def login(self, username: str, password: str) -> tuple[bool, str]:
        """Attempt login. Returns (success, message)."""
        try:
            user = self.ctx.auth.authenticate(username, password)
        except AuthError as exc:
            return False, str(exc)
        current_session.login(user)
        return True, "ok"

    def must_change_password(self) -> bool:
        user = current_session.user
        return bool(user and self.ctx.auth.must_change_password(user.id))

    def change_password(self, new_password: str) -> tuple[bool, str]:
        user = current_session.require_authenticated()
        from ..core.exceptions import ValidationError
        try:
            self.ctx.auth.change_password(user.id, new_password)
        except ValidationError as exc:
            return False, str(exc)
        return True, "Password updated."

    def logout(self) -> None:
        current_session.logout()
