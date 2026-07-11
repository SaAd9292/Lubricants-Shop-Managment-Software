"""User accounts management (admin).

Security & integrity rules enforced here (not just in the UI):
  * passwords stored only as PBKDF2 hash + per-user salt
  * usernames are unique (case-insensitive)
  * you cannot deactivate or demote the LAST active admin (lockout guard)
  * you cannot deactivate your own account while logged in
New users get must_change_pw=1 so they set their own password on first login.
"""
from __future__ import annotations

from typing import Any

from ..core import permissions as perms
from ..core import security
from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

VALID_ROLES = ("admin", "cashier")
MIN_PW_LEN = 6


class UserService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- reads --------------------------------------------------------
    def list_users(self, *, search: str = "", role: str | None = None,
                   only_active: bool = False, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        clauses, params = [], []
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(username LIKE ? OR full_name LIKE ?)")
            params += [like, like]
        if role:
            clauses.append("role = ?")
            params.append(role)
        if only_active:
            clauses.append("is_active = 1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.db.query_one(f"SELECT COUNT(*) n FROM users {where}", tuple(params))["n"]
        rows = self.db.query(
            f"SELECT id, username, full_name, role, is_active, must_change_pw, "
            f"last_login_at, created_at FROM users {where} "
            f"ORDER BY username COLLATE NOCASE LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)))
        return {"rows": [dict(r) for r in rows], "total": total}

    def get(self, user_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT id, username, full_name, role, is_active, must_change_pw, "
            "last_login_at, created_at, permissions FROM users WHERE id = ?", (user_id,))
        if not row:
            raise NotFoundError(f"User {user_id} not found")
        d = dict(row)
        d["permissions"] = sorted(perms.parse(d.get("permissions")))
        return d

    def _active_admin_count(self, exclude_id: int | None = None) -> int:
        if exclude_id:
            row = self.db.query_one(
                "SELECT COUNT(*) n FROM users WHERE role='admin' AND is_active=1 AND id != ?",
                (exclude_id,))
        else:
            row = self.db.query_one(
                "SELECT COUNT(*) n FROM users WHERE role='admin' AND is_active=1")
        return row["n"]

    # -- writes -------------------------------------------------------
    def create_user(self, *, username: str, password: str, role: str,
                    full_name: str = "", must_change_pw: bool = True,
                    permissions: list[str] | None = None,
                    actor_id: int | None = None) -> int:
        username = (username or "").strip()
        if not username:
            raise ValidationError("Username is required.")
        if role not in VALID_ROLES:
            raise ValidationError(f"Role must be one of {VALID_ROLES}.")
        if not password or len(password) < MIN_PW_LEN:
            raise ValidationError(f"Password must be at least {MIN_PW_LEN} characters.")
        if self.db.query_one("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)):
            raise ValidationError(f"Username '{username}' already exists.")
        pwd_hash, salt, iters = security.hash_password(password)
        perm_json = perms.serialize(
            permissions if permissions is not None else perms.DEFAULT_CASHIER)
        cur = self.db.execute(
            "INSERT INTO users (username, full_name, password_hash, password_salt, "
            "pwd_iterations, role, must_change_pw, permissions) VALUES (?,?,?,?,?,?,?,?)",
            (username, full_name.strip(), pwd_hash, salt, iters, role,
             1 if must_change_pw else 0, perm_json))
        self.audit.record(action="CREATE", user_id=actor_id, entity_type="user",
                          entity_id=cur.lastrowid, details={"username": username, "role": role})
        log.info("Created user '%s' (role=%s)", username, role)
        return cur.lastrowid

    def update_user(self, user_id: int, *, full_name: str | None = None,
                    role: str | None = None, permissions: list[str] | None = None,
                    actor_id: int | None = None) -> None:
        user = self.get(user_id)
        fields: dict[str, Any] = {}
        if full_name is not None:
            fields["full_name"] = full_name.strip()
        if role is not None:
            if role not in VALID_ROLES:
                raise ValidationError(f"Role must be one of {VALID_ROLES}.")
            # demoting the last active admin would lock everyone out
            if user["role"] == "admin" and role != "admin" \
                    and user["is_active"] and self._active_admin_count(exclude_id=user_id) == 0:
                raise ValidationError("Cannot change role: this is the last active admin.")
            fields["role"] = role
        if permissions is not None:
            fields["permissions"] = perms.serialize(permissions)
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE users SET {set_clause} WHERE id = ?",
                        (*fields.values(), user_id))
        self.audit.record(action="UPDATE", user_id=actor_id, entity_type="user",
                          entity_id=user_id, details={"fields": list(fields)})

    def reset_password(self, user_id: int, new_password: str, *,
                       force_change: bool = True, actor_id: int | None = None) -> None:
        self.get(user_id)
        if not new_password or len(new_password) < MIN_PW_LEN:
            raise ValidationError(f"Password must be at least {MIN_PW_LEN} characters.")
        pwd_hash, salt, iters = security.hash_password(new_password)
        self.db.execute(
            "UPDATE users SET password_hash=?, password_salt=?, pwd_iterations=?, "
            "must_change_pw=? WHERE id=?",
            (pwd_hash, salt, iters, 1 if force_change else 0, user_id))
        self.audit.record(action="PASSWORD_RESET", user_id=actor_id, entity_type="user",
                          entity_id=user_id)
        log.info("Password reset for user_id=%s", user_id)

    def set_active(self, user_id: int, active: bool, *, actor_id: int | None = None) -> None:
        user = self.get(user_id)
        if not active:
            if actor_id == user_id:
                raise ValidationError("You cannot deactivate your own account.")
            if user["role"] == "admin" and user["is_active"] \
                    and self._active_admin_count(exclude_id=user_id) == 0:
                raise ValidationError("Cannot deactivate the last active admin.")
        self.db.execute("UPDATE users SET is_active = ? WHERE id = ?",
                        (1 if active else 0, user_id))
        self.audit.record(action="UPDATE", user_id=actor_id, entity_type="user",
                          entity_id=user_id, details={"is_active": bool(active)})
        log.info("Set user_id=%s active=%s", user_id, active)

    def delete_user(self, user_id: int, *, actor_id: int | None = None) -> None:
        """Permanently delete a user. Referentially safe: every FK to users is
        ON DELETE SET NULL and sales keep a cashier_name snapshot, so invoice
        history stays intact (only the live account link is removed).

        Guards mirror deactivation: you cannot delete your own account, nor the
        last active admin (which would lock everyone out). For a user with
        history, deactivating is usually preferable so the audit link survives.
        """
        user = self.get(user_id)  # raises NotFound if missing
        if actor_id == user_id:
            raise ValidationError("You cannot delete your own account.")
        if user["role"] == "admin" and self._active_admin_count(exclude_id=user_id) == 0:
            raise ValidationError("Cannot delete the last active admin account.")
        # record BEFORE the row goes away (details keep the username for the log)
        self.audit.record(action="DELETE", user_id=actor_id, entity_type="user",
                          entity_id=user_id,
                          details={"username": user["username"], "role": user["role"]})
        self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        log.warning("Deleted user_id=%s (%s) by actor=%s",
                    user_id, user["username"], actor_id)
