"""Add / Edit user dialog.

Create mode sets an initial password; edit mode changes name / role / privileges
(passwords are changed via the Reset Password action).

Privileges: admins implicitly have everything, so the privilege checkboxes only
apply to cashiers. Each checkbox maps to a screen or action permission key
(see core.permissions). Sensitive screens (Users, Settings, Backup, Audit) are
never listed here.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ..controllers.user_controller import UserController
from ..core import permissions as perms

ROLES = ["cashier", "admin"]


class UserEditDialog(QDialog):
    def __init__(self, controller: UserController, user_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.user_id = user_id
        self._perm_boxes: dict[str, QCheckBox] = {}
        self.setWindowTitle("Edit User" if user_id else "Add User")
        self.setMinimumWidth(480)
        self._build_ui()
        if user_id:
            self._load()
        else:
            # new cashier starts with the sensible default screens ticked
            for key in perms.DEFAULT_CASHIER:
                if key in self._perm_boxes:
                    self._perm_boxes[key].setChecked(True)
        self._sync_privileges()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)

        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.role = QComboBox()
        self.role.addItems(ROLES)
        self.role.currentTextChanged.connect(self._sync_privileges)
        form.addRow("Username *", self.username)
        form.addRow("Full name", self.full_name)
        form.addRow("Role *", self.role)

        if self.user_id is None:
            self.password = QLineEdit()
            self.password.setEchoMode(QLineEdit.Password)
            self.password.setPlaceholderText("Initial password (min 6 chars)")
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.Password)
            self.confirm.setPlaceholderText("Confirm password")
            self.force = QCheckBox("Require password change on first login")
            self.force.setChecked(True)
            form.addRow("Password *", self.password)
            form.addRow("Confirm *", self.confirm)
            form.addRow("", self.force)
        else:
            self.username.setReadOnly(True)
        root.addLayout(form)

        # -- privileges (cashiers only) --
        self.priv_box = QGroupBox("Privileges")
        pv = QVBoxLayout(self.priv_box)
        self.priv_hint = QLabel(
            "Choose what this cashier can access and do. (Admins always have "
            "full access.)")
        self.priv_hint.setObjectName("Muted")
        self.priv_hint.setWordWrap(True)
        pv.addWidget(self.priv_hint)

        cols = QHBoxLayout()
        cols.addLayout(self._perm_column("Screens", perms.SCREEN_PERMISSIONS))
        cols.addLayout(self._perm_column("Actions", perms.ACTION_PERMISSIONS))
        pv.addLayout(cols)
        root.addWidget(self.priv_box)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    def _perm_column(self, title: str, items) -> QVBoxLayout:
        col = QVBoxLayout()
        hdr = QLabel(title)
        hdr.setStyleSheet("font-weight:700;")
        col.addWidget(hdr)
        grid = QGridLayout()
        grid.setVerticalSpacing(2)
        for i, (key, label) in enumerate(items):
            cb = QCheckBox(label)
            self._perm_boxes[key] = cb
            grid.addWidget(cb, i, 0)
        col.addLayout(grid)
        col.addStretch(1)
        return col

    def _sync_privileges(self) -> None:
        """Privileges apply to cashiers only; hide them for the admin role."""
        is_cashier = self.role.currentText() == "cashier"
        self.priv_box.setVisible(is_cashier)
        self.adjustSize()

    def _collect_permissions(self) -> list[str]:
        return [k for k, cb in self._perm_boxes.items() if cb.isChecked()]

    def _load(self) -> None:
        u = self.controller.get(self.user_id)
        self.username.setText(u["username"])
        self.full_name.setText(u.get("full_name") or "")
        self.role.setCurrentText(u["role"])
        granted = set(u.get("permissions") or [])
        for key, cb in self._perm_boxes.items():
            cb.setChecked(key in granted)

    def _save(self) -> None:
        role = self.role.currentText()
        permissions = self._collect_permissions() if role == "cashier" else None
        if self.user_id is None:
            if not self.username.text().strip():
                QMessageBox.warning(self, "Required", "Username is required.")
                return
            if self.password.text() != self.confirm.text():
                QMessageBox.warning(self, "Mismatch", "Passwords do not match.")
                return
            ok, msg, _ = self.controller.create(
                username=self.username.text().strip(),
                password=self.password.text(),
                role=role,
                full_name=self.full_name.text().strip(),
                must_change_pw=self.force.isChecked(),
                permissions=permissions,
            )
        else:
            ok, msg, _ = self.controller.update(
                self.user_id, full_name=self.full_name.text().strip(),
                role=role, permissions=permissions)
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)
