"""Main application window: sidebar navigation + top header bar + stacked pages.

Identity hierarchy (no duplicated titles): the sidebar shows the PRODUCT
(Penguix), the header shows the SHOP (from company settings) + date + signed-in
user, and each page prints its own section title.

Navigation is role-aware:
  * admin   -> all modules
  * cashier -> POS, Sales History, Dashboard only (view sales)
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..config import resource_path
from ..core.logging_config import get_logger
from ..core.session import current_session
from ..ui.icons import make_icon
from .audit_view import AuditView
from .backup_view import BackupView
from .dashboard_view import DashboardView
from .expenses_view import ExpensesView
from .placeholder_view import PlaceholderView
from .pos_view import POSView
from .products_view import ProductsView
from .purchases_view import PurchasesView
from .reports_view import ReportsView
from .sales_view import SalesView
from .settings_view import SettingsView
from .suppliers_view import SuppliersView
from .taxonomy_view import TaxonomyView
from .users_view import UsersView

log = get_logger(__name__)

# (label, key, admin_only)
NAV_ITEMS = [
    ("Dashboard", "dashboard", False),
    ("Sale", "pos", False),
    ("Sales History", "sales", False),
    ("Products", "products", True),
    ("Categories & Brands", "taxonomy", True),
    ("Suppliers", "suppliers", True),
    ("Purchases", "purchases", True),
    ("Expenses", "expenses", True),
    ("Reports", "reports", True),
    ("Users", "users", True),
    ("Audit Log", "audit", True),
    ("Backup & Restore", "backup", True),
    ("Settings", "settings", True),
]


def _initials(name: str) -> str:
    parts = (name or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, app) -> None:
        super().__init__()
        self.ctx = ctx
        self.app = app
        self._pages: dict[str, int] = {}
        self._nav_buttons: dict[str, object] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        company = self.ctx.company.get_company()
        shop_name = company.get("shop_name") or "My Shop"
        self.setWindowTitle(f"{shop_name} — Penguix")
        self.resize(1200, 760)
        self.setMinimumSize(980, 640)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_content(shop_name), 1)

        user = current_session.user
        who = f"{user.full_name or user.username} ({user.role})" if user else "—"
        self.statusBar().showMessage(f"{shop_name}   |   Signed in as {who}")

        self._go("dashboard")

    # -- sidebar ------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 14, 10, 12)
        side.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 6, 8)
        header.setSpacing(9)
        self.logo = QLabel()
        self.logo.setObjectName("BrandLogo")
        self.logo.setFixedSize(34, 34)
        self.logo.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(resource_path("assets", "penguix.png")))
        if not pix.isNull():
            self.logo.setPixmap(pix.scaled(26, 26, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
        header.addWidget(self.logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        name = QLabel("Penguix")
        name.setObjectName("BrandName")
        sub = QLabel("POS System")
        sub.setObjectName("BrandSub")
        brand_box.addWidget(name)
        brand_box.addWidget(sub)
        header.addLayout(brand_box, 1)
        side.addLayout(header)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        side.addWidget(divider)
        side.addSpacing(6)

        self.stack = QStackedWidget()
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        is_admin = current_session.is_admin
        for label, key, admin_only in NAV_ITEMS:
            if admin_only and not is_admin:
                continue
            btn = QPushButton(label)
            btn.setCheckable(True)
            page = self._make_page(key, label)
            idx = self.stack.addWidget(page)
            self._pages[key] = idx
            btn.clicked.connect(lambda _=False, k=key: self._go(k))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            normal_icon = make_icon(key, "#6b7280")
            active_icon = make_icon(key, "#2563eb")
            if not normal_icon.isNull():
                btn.setIcon(normal_icon)
                btn.setIconSize(QSize(18, 18))
                btn.toggled.connect(
                    lambda checked, b=btn, ni=normal_icon, ai=active_icon:
                    b.setIcon(ai if checked else ni))
            side.addWidget(btn)

        side.addStretch(1)

        divider2 = QFrame()
        divider2.setFrameShape(QFrame.HLine)
        side.addWidget(divider2)
        logout_btn = QPushButton("Log out")
        logout_btn.setObjectName("Secondary")
        logout_btn.clicked.connect(self._logout)
        side.addWidget(logout_btn)
        return sidebar

    # -- content (header bar + stacked pages) -------------------------
    def _build_content(self, shop_name: str) -> QWidget:
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        header = QWidget()
        header.setObjectName("HeaderBar")
        header.setFixedHeight(64)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 10, 20, 10)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.header_title = QLabel(shop_name)
        self.header_title.setObjectName("HeaderTitle")
        self.header_sub = QLabel(datetime.now().strftime("%A, %d %B %Y"))
        self.header_sub.setObjectName("HeaderSub")
        title_box.addWidget(self.header_title)
        title_box.addWidget(self.header_sub)
        hl.addLayout(title_box)
        hl.addStretch(1)

        user = current_session.user
        uname = (user.full_name or user.username) if user else "—"
        role = user.role.capitalize() if user else ""
        user_box = QVBoxLayout()
        user_box.setSpacing(0)
        un = QLabel(uname)
        un.setObjectName("UserName")
        un.setAlignment(Qt.AlignRight)
        ur = QLabel(role)
        ur.setObjectName("UserRole")
        ur.setAlignment(Qt.AlignRight)
        user_box.addWidget(un)
        user_box.addWidget(ur)
        hl.addLayout(user_box)

        avatar = QLabel(_initials(uname))
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignCenter)
        hl.addSpacing(10)
        hl.addWidget(avatar)

        col.addWidget(header)
        col.addWidget(self.stack, 1)
        return wrap

    # -- pages --------------------------------------------------------
    def _make_page(self, key: str, label: str) -> QWidget:
        if key == "dashboard":
            return DashboardView(self.ctx, navigate=self._navigate_to)
        if key == "products":
            return ProductsView(self.ctx)
        if key == "suppliers":
            return SuppliersView(self.ctx)
        if key == "purchases":
            return PurchasesView(self.ctx)
        if key == "expenses":
            return ExpensesView(self.ctx)
        if key == "pos":
            return POSView(self.ctx)
        if key == "sales":
            return SalesView(self.ctx)
        if key == "reports":
            return ReportsView(self.ctx)
        if key == "users":
            return UsersView(self.ctx)
        if key == "audit":
            return AuditView(self.ctx)
        if key == "backup":
            return BackupView(self.ctx)
        if key == "taxonomy":
            return TaxonomyView(self.ctx)
        if key == "settings":
            return SettingsView(self.ctx, on_saved=self._on_settings_saved)
        return PlaceholderView(label)

    # -- navigation ---------------------------------------------------
    def _go(self, key: str) -> None:
        """Switch page by key: set stack + check the matching nav button.

        Every data view is built once and cached in the stack, so its table
        would otherwise show a stale snapshot from when the app started (e.g.
        stock that doesn't drop after a sale until re-login). Re-pull the
        target page's data on each navigation so every screen reflects the
        latest committed state instantly.
        """
        idx = self._pages.get(key)
        if idx is None:
            return
        self.stack.setCurrentIndex(idx)
        self._refresh_page(self.stack.widget(idx))
        btn = self._nav_buttons.get(key)
        if btn is not None:
            btn.setChecked(True)

    @staticmethod
    def _refresh_page(widget) -> None:
        """Re-pull a page's data if it exposes a refresh() or _reload() hook.
        Views without one (Settings, Reports, POS) are simply left as-is."""
        for name in ("refresh", "_reload"):
            fn = getattr(widget, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # a refresh must never break navigation
                    log.exception("Refresh failed for %s", type(widget).__name__)
                return

    def _navigate_to(self, key: str) -> None:
        """Used by clickable dashboard cards."""
        self._go(key)

    def _on_settings_saved(self) -> None:
        """Reflect a shop-name change live (window title + header + status bar)."""
        company = self.ctx.company.get_company()
        shop_name = company.get("shop_name") or "My Shop"
        self.setWindowTitle(f"{shop_name} — Penguix")
        self.header_title.setText(shop_name)
        user = current_session.user
        who = f"{user.full_name or user.username} ({user.role})" if user else "—"
        self.statusBar().showMessage(f"{shop_name}   |   Signed in as {who}")
        dash = self.stack.widget(self._pages.get("dashboard", 0))
        if isinstance(dash, DashboardView):
            dash.refresh()

    def _logout(self) -> None:
        current_session.logout()
        self._logged_out = True
        self.close()
