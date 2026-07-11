"""Authentication and user-account operations.

Security notes:
  * Passwords verified with constant-time PBKDF2 comparison.
  * Generic failure message (no "user not found" vs "bad password" leak).
  * Inactive users cannot log in.
  * Successful/failed logins are audited; failures logged at WARNING.
  * Login does not reveal which accounts exist.
"""
from __future__ import annotations

from ..core import security
from ..core.exceptions import AuthError, ValidationError
from ..core.logging_config import get_logger
from ..core import permissions as perms
from ..core.session import CurrentUser
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

_GENERIC_FAIL = "Invalid username or password."


class AuthService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    def authenticate(self, username: str, password: str) -> CurrentUser:
        username = (username or "").strip()
        if not username or not password:
            raise AuthError(_GENERIC_FAIL)

        row = self.db.query_one(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        )
        if row is None or not row["is_active"]:
            log.warning("Failed login for username=%r (no/inactive account)", username)
            self.audit.record(action="LOGIN_FAILED", username=username)
            raise AuthError(_GENERIC_FAIL)

        ok = security.verify_password(
            password, row["password_hash"], row["password_salt"], row["pwd_iterations"]
        )
        if not ok:
            log.warning("Failed login for username=%r (bad password)", username)
            self.audit.record(action="LOGIN_FAILED", user_id=row["id"], username=username)
            raise AuthError(_GENERIC_FAIL)

        self.db.execute(
            "UPDATE users SET last_login_at = strftime('%Y-%m-%d %H:%M:%S','now') "
            "WHERE id = ?",
            (row["id"],),
        )
        self.audit.record(action="LOGIN", user_id=row["id"], username=username)
        log.info("User '%s' (role=%s) logged in", username, row["role"])
        perm_raw = row["permissions"] if "permissions" in row.keys() else None
        return CurrentUser(
            id=row["id"], username=row["username"],
            full_name=row["full_name"], role=row["role"],
            permissions=frozenset(perms.parse(perm_raw)),
        )

    def must_change_password(self, user_id: int) -> bool:
        row = self.db.query_one("SELECT must_change_pw FROM users WHERE id = ?", (user_id,))
        return bool(row and row["must_change_pw"])

    def change_password(self, user_id: int, new_password: str) -> None:
        if not new_password or len(new_password) < 6:
            raise ValidationError("Password must be at least 6 characters.")
        pwd_hash, salt, iters = security.hash_password(new_password)
        self.db.execute(
            "UPDATE users SET password_hash=?, password_salt=?, pwd_iterations=?, "
            "must_change_pw=0 WHERE id=?",
            (pwd_hash, salt, iters, user_id),
        )
        self.audit.record(action="PASSWORD_CHANGED", user_id=user_id, entity_type="user",
                          entity_id=user_id)
        log.info("Password changed for user_id=%s", user_id)
