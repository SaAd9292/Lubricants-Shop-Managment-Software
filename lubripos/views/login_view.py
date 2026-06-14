"""Login dialog. Shows shop name from settings (white-label) and authenticates.

On first login with the seeded admin, the user is forced to set a new
password before entering the app.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.auth_controller import AuthController


class LoginDialog(QDialog):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = AuthController(ctx)
        self._build_ui()

    def _build_ui(self) -> None:
        company = self.ctx.company.get_company()
        shop_name = company.get("shop_name") or "Penguix"

        self.setWindowTitle(f"{shop_name} — Sign in")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel(shop_name)
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Sign in to continue")
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        root.addWidget(subtitle)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Password")
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        root.addWidget(form_host)

        self.error = QLabel("")
        self.error.setStyleSheet("color: #ef4444;")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        btn = QPushButton("Sign in")
        btn.clicked.connect(self._attempt_login)
        root.addWidget(btn)

        self.password.returnPressed.connect(self._attempt_login)
        self.username.setFocus()

    def _attempt_login(self) -> None:
        ok, msg = self.controller.login(self.username.text(), self.password.text())
        if not ok:
            self.error.setText(msg)
            self.password.clear()
            return
        if self.controller.must_change_password():
            if not self._force_password_change():
                self.controller.logout()
                self.error.setText("Password change required to continue.")
                return
        self.accept()

    def _force_password_change(self) -> bool:
        QMessageBox.information(
            self, "Set a new password",
            "This account is using a temporary password. Please set a new one.",
        )
        while True:
            new_pw, ok = QInputDialog.getText(
                self, "New password", "Enter a new password (min 6 chars):",
                QLineEdit.Password,
            )
            if not ok:
                return False
            success, msg = self.controller.change_password(new_pw)
            if success:
                QMessageBox.information(self, "Done", msg)
                return True
            QMessageBox.warning(self, "Invalid", msg)
