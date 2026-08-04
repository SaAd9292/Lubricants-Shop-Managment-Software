"""Login dialog — a branded, modern sign-in screen.

Shows the shop identity (white-label: name + logo from settings) on a gradient
header, then a clean sign-in form. On first login with the seeded admin, the
user is forced to set a new password before entering the app.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..config import resource_path
from ..controllers.auth_controller import AuthController

ACCENT = "#2563eb"
_GRAD_A = "#2563eb"
_GRAD_B = "#4338ca"
_INK = "#0f172a"
_MUTE = "#94a3b8"
_LABEL = "color:#475569;font-size:12px;font-weight:600;"

_FORM_QSS = f"""
QLineEdit {{
    background:#f8fafc; border:1px solid #e2e8f0; border-radius:9px;
    padding:10px 12px; font-size:13px; color:{_INK};
}}
QLineEdit:focus {{ border:1px solid {ACCENT}; background:#ffffff; }}
QPushButton#SignIn {{
    background:{ACCENT}; color:#ffffff; border:none; border-radius:9px;
    font-size:14px; font-weight:600;
}}
QPushButton#SignIn:hover {{ background:#1d4ed8; }}
QPushButton#SignIn:pressed {{ background:#1e40af; }}
"""


def _initials(name: str) -> str:
    parts = [w for w in (name or "").split() if w]
    if not parts:
        return "P"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


class _GradientHeader(QFrame):
    """The branded top band: gradient background with the shop logo + name."""

    def __init__(self, shop_name: str, pix: QPixmap | None) -> None:
        super().__init__()
        self.setFixedHeight(172)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 0, 24, 0)
        v.setSpacing(3)
        v.addStretch(1)

        logo = QLabel()
        logo.setFixedSize(64, 64)
        logo.setAlignment(Qt.AlignCenter)
        if pix is not None and not pix.isNull():
            logo.setStyleSheet("background:#ffffff;border-radius:32px;")
            logo.setPixmap(pix.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo.setStyleSheet("background:#ffffff;border-radius:32px;"
                               f"color:{ACCENT};font-size:23px;font-weight:800;")
            logo.setText(_initials(shop_name))
        v.addWidget(logo, 0, Qt.AlignHCenter)

        name = QLabel(shop_name)
        name.setAlignment(Qt.AlignHCenter)
        name.setStyleSheet("color:#ffffff;font-size:20px;font-weight:800;")
        sub = QLabel("POS SYSTEM")
        sub.setAlignment(Qt.AlignHCenter)
        sub.setStyleSheet("color:rgba(255,255,255,0.82);font-size:11px;"
                          "font-weight:600;letter-spacing:2px;")
        v.addSpacing(10)
        v.addWidget(name)
        v.addWidget(sub)
        v.addStretch(1)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor(_GRAD_A))
        g.setColorAt(1.0, QColor(_GRAD_B))
        p.fillRect(self.rect(), g)
        # soft translucent circles for a subtle "state of the art" flourish
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawEllipse(self.width() - 40, -40, 120, 120)
        p.drawEllipse(-30, self.height() - 50, 90, 90)
        p.end()


class LoginDialog(QDialog):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = AuthController(ctx)
        self._build_ui()

    def _logo_pixmap(self, company: dict) -> QPixmap | None:
        lp = company.get("logo_path")
        if lp:
            pix = QPixmap(str(lp))
            if not pix.isNull():
                return pix
        pix = QPixmap(str(resource_path("assets", "penguix.png")))
        return pix if not pix.isNull() else None

    def _build_ui(self) -> None:
        company = self.ctx.company.get_company()
        shop_name = company.get("shop_name") or "Penguix"

        self.setWindowTitle(f"{shop_name} — Sign in")
        self.setFixedWidth(420)
        self.setStyleSheet(_FORM_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(_GradientHeader(shop_name, self._logo_pixmap(company)))

        body = QWidget()
        body.setStyleSheet("background:#ffffff;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(32, 26, 32, 24)
        bl.setSpacing(6)

        welcome = QLabel("Welcome back")
        welcome.setStyleSheet(f"font-size:17px;font-weight:700;color:{_INK};")
        hint = QLabel("Sign in to continue")
        hint.setStyleSheet(f"color:{_MUTE};font-size:12px;")
        bl.addWidget(welcome)
        bl.addWidget(hint)
        bl.addSpacing(14)

        u_lbl = QLabel("Username")
        u_lbl.setStyleSheet(_LABEL)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Enter your username")
        self.username.setMinimumHeight(20)
        bl.addWidget(u_lbl)
        bl.addWidget(self.username)
        bl.addSpacing(12)

        p_lbl = QLabel("Password")
        p_lbl.setStyleSheet(_LABEL)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Enter your password")
        self.password.setMinimumHeight(20)
        bl.addWidget(p_lbl)
        bl.addWidget(self.password)

        self.error = QLabel("")
        self.error.setStyleSheet("color:#ef4444;font-size:12px;")
        self.error.setWordWrap(True)
        bl.addSpacing(6)
        bl.addWidget(self.error)

        self.sign_in_btn = QPushButton("Sign in")
        self.sign_in_btn.setObjectName("SignIn")
        self.sign_in_btn.setMinimumHeight(46)
        self.sign_in_btn.setCursor(Qt.PointingHandCursor)
        # style the button DIRECTLY (not only via the dialog stylesheet) so it can
        # never render blank due to an app-wide stylesheet cascade quirk.
        self.sign_in_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#ffffff;border:none;"
            "border-radius:9px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#1d4ed8;}"
            "QPushButton:pressed{background:#1e40af;}")
        self.sign_in_btn.clicked.connect(self._attempt_login)
        bl.addSpacing(12)
        bl.addWidget(self.sign_in_btn)

        foot = QLabel("Secured by Penguix POS")
        foot.setAlignment(Qt.AlignHCenter)
        foot.setStyleSheet(f"color:{_MUTE};font-size:10px;")
        bl.addSpacing(14)
        bl.addWidget(foot)

        root.addWidget(body)

        self.username.returnPressed.connect(self.password.setFocus)
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
