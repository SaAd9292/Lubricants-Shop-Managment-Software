"""Holds the currently authenticated user for the running app instance.

Single-process desktop app => a module-level singleton is appropriate.
Controllers check `current_session.require_role(...)` before privileged ops;
role checks live in code, NOT only hidden UI buttons.
"""
from __future__ import annotations

from dataclasses import dataclass

from .exceptions import PermissionDenied


@dataclass
class CurrentUser:
    id: int
    username: str
    full_name: str | None
    role: str  # 'admin' | 'cashier'
    permissions: frozenset[str] = frozenset()


class Session:
    def __init__(self) -> None:
        self._user: CurrentUser | None = None

    @property
    def user(self) -> CurrentUser | None:
        return self._user

    @property
    def is_authenticated(self) -> bool:
        return self._user is not None

    @property
    def is_admin(self) -> bool:
        return self._user is not None and self._user.role == "admin"

    def login(self, user: CurrentUser) -> None:
        self._user = user

    def logout(self) -> None:
        self._user = None

    def require_authenticated(self) -> CurrentUser:
        if self._user is None:
            raise PermissionDenied("Not authenticated")
        return self._user

    def require_role(self, *roles: str) -> CurrentUser:
        user = self.require_authenticated()
        if user.role not in roles:
            raise PermissionDenied(
                f"Action requires role(s) {roles}; current role is '{user.role}'"
            )
        return user

    def can(self, permission: str) -> bool:
        """Admins can do anything; others need the explicit grant."""
        if self._user is None:
            return False
        if self._user.role == "admin":
            return True
        return permission in self._user.permissions

    def require_permission(self, permission: str) -> CurrentUser:
        user = self.require_authenticated()
        if user.role == "admin" or permission in user.permissions:
            return user
        raise PermissionDenied(f"You do not have the '{permission}' privilege.")


# App-wide session instance.
current_session = Session()
