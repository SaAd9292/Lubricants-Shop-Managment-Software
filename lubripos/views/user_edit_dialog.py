"""Add / Edit user dialog. Create mode sets an initial password; edit mode
changes name/role only (passwords are changed via the Reset Password action).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from ..controllers.user_controller import UserController

ROLES = ["cashier", "admin"]


class UserEditDialog(QDialog):
    def __init__(self, controller: UserController, user_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.user_id = user_id
        self.setWindowTitle("Edit User" if user_id else "Add User")
        self.setMinimumWidth(400)
        self._build_ui()
        if user_id:
            self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)

        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.role = QComboBox()
        self.role.addItems(ROLES)
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

    def _load(self) -> None:
        u = self.controller.get(self.user_id)
        self.username.setText(u["username"])
        self.full_name.setText(u.get("full_name") or "")
        self.role.setCurrentText(u["role"])

    def _save(self) -> None:
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
                role=self.role.currentText(),
                full_name=self.full_name.text().strip(),
                must_change_pw=self.force.isChecked(),
            )
        else:
            ok, msg, _ = self.controller.update(
                self.user_id, full_name=self.full_name.text().strip(),
                role=self.role.currentText())
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)
