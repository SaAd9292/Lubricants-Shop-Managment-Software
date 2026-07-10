"""User Management page (admin)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.user_controller import UserController
from .user_edit_dialog import UserEditDialog

COLUMNS = ["Username", "Full Name", "Role", "Status", "Last Login"]


class UsersView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = UserController(ctx)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Users")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add User")
        add_btn.clicked.connect(self._add)
        header.addWidget(add_btn)
        root.addLayout(header)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = 'No users found.'
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda: self._edit())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        for label, slot in [("Edit", self._edit), ("Reset Password", self._reset),
                            ("Activate / Deactivate", self._toggle_active)]:
            b = QPushButton(label)
            b.setObjectName("Secondary")
            b.clicked.connect(slot)
            footer.addWidget(b)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.clicked.connect(self._delete)
        footer.addWidget(self.delete_btn)
        footer.addStretch(1)
        root.addLayout(footer)

    def _reload(self) -> None:
        rows = self.controller.list()["rows"]
        self.table.setRowCount(len(rows))
        for r, u in enumerate(rows):
            values = [
                u["username"], u.get("full_name") or "", u["role"],
                "Active" if u["is_active"] else "Inactive",
                (u.get("last_login_at") or "Never")[:16],
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, u["id"])
                    item.setData(Qt.UserRole + 1, bool(u["is_active"]))
                if not u["is_active"]:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole), item.data(Qt.UserRole + 1)

    def _need_selection(self):
        uid, active = self._selected()
        if uid is None:
            QMessageBox.information(self, "Select a user", "Please select a row first.")
        return uid, active

    def _add(self) -> None:
        if UserEditDialog(self.controller).exec():
            self._reload()

    def _edit(self) -> None:
        uid, _ = self._need_selection()
        if uid is None:
            return
        if UserEditDialog(self.controller, user_id=uid).exec():
            self._reload()

    def _reset(self) -> None:
        uid, _ = self._need_selection()
        if uid is None:
            return
        pw, ok = QInputDialog.getText(self, "Reset password",
                                      "New password (min 6 chars):", QLineEdit.Password)
        if not ok:
            return
        success, msg, _ = self.controller.reset_password(uid, pw, force_change=True)
        if success:
            QMessageBox.information(self, "Done",
                                    "Password reset. The user must change it on next login.")
        else:
            QMessageBox.warning(self, "Could not reset", msg)

    def _toggle_active(self) -> None:
        uid, active = self._need_selection()
        if uid is None:
            return
        success, msg, _ = self.controller.set_active(uid, not active)
        if success:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)

    def _delete(self) -> None:
        uid, _ = self._need_selection()
        if uid is None:
            return
        row = self.table.currentRow()
        username = self.table.item(row, 0).text() if row >= 0 else "this user"
        confirm = QMessageBox.warning(
            self, "Delete user",
            f"Permanently delete '{username}'?\n\n"
            "Invoice history is kept (each sale stores the cashier's name), but "
            "the account is removed for good and cannot be recovered.\n\n"
            "Tip: if you only want to stop this person signing in, use "
            "Activate / Deactivate instead.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if confirm != QMessageBox.Yes:
            return
        success, msg, _ = self.controller.delete(uid)
        if success:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)
