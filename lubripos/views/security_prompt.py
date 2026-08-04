"""Re-authentication prompt for destructive admin actions.

Some actions (deleting a backup file, resetting/flushing all shop data) are
irreversible, so we re-confirm the signed-in admin's password before doing them
— even though they're already logged in. This guards against someone using an
unattended, already-open admin session.
"""
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ..app_context import AppContext
from ..core.session import current_session


def require_admin_password(parent, ctx: AppContext) -> bool:
    """Prompt for the current admin's password and verify it. Returns True only
    if an admin is signed in and typed the correct password."""
    user = current_session.user
    if not user or user.role != "admin":
        QMessageBox.warning(parent, "Not allowed",
                            "Only an administrator can perform this action.")
        return False
    pw, ok = QInputDialog.getText(
        parent, "Admin password required",
        f"Enter the password for '{user.username}' to confirm this action:",
        QLineEdit.Password)
    if not ok:
        return False
    if ctx.auth.verify_password(user.id, pw):
        return True
    QMessageBox.warning(parent, "Incorrect password",
                        "That password is incorrect. Action cancelled.")
    return False
