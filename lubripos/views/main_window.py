"""Main application window: sidebar navigation + stacked content pages.

Navigation is role-aware:
  * admin   -> all modules
  * cashier -> POS, Sales History, Dashboard only (view sales)
Module pages are added as each build step lands. Live so far: Dashboard,
Products, Suppliers, Purchases, Settings. The rest are placeholders.
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.session import current_session
from ..ui.icons import make_icon
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
    ("Backup & Restore", "backup", True),
    ("Settings", "settings", True),
]


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
        shop_name = company.get("shop_name") or "Penguix"
        self.setWindowTitle(f"{shop_name} — Penguix")
        self.resize(1180, 740)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Sidebar ---
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 10)
        side.setSpacing(4)

        self.brand = QLabel(shop_name)
        self.brand.setObjectName("BrandLabel")
        self.brand.setWordWrap(True)
        side.addWidget(self.brand)

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
            btn.clicked.connect(lambda _=False, i=idx: self.stack.setCurrentIndex(i))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            normal_icon = make_icon(key, "#475569")
            active_icon = make_icon(key, "#ffffff")
            if not normal_icon.isNull():
                btn.setIcon(normal_icon)
                btn.setIconSize(QSize(18, 18))
                btn.toggled.connect(
                    lambda checked, b=btn, ni=normal_icon, ai=active_icon:
                    b.setIcon(ai if checked else ni))
            side.addWidget(btn)
            if key == "dashboard":
                btn.setChecked(True)

        side.addStretch(1)

        logout_btn = QPushButton("Log out")
        logout_btn.setObjectName("Secondary")
        logout_btn.clicked.connect(self._logout)
        side.addWidget(logout_btn)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)

        # --- Status bar ---
        user = current_session.user
        who = f"{user.full_name or user.username} ({user.role})" if user else "—"
        self.statusBar().showMessage(f"{shop_name}   |   Signed in as {who}")

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
        if key == "backup":
            return BackupView(self.ctx)
        if key == "taxonomy":
            return TaxonomyView(self.ctx)
        if key == "settings":
            return SettingsView(self.ctx, on_saved=self._on_settings_saved)
        return PlaceholderView(label)

    def _navigate_to(self, key: str) -> None:
        """Switch to a page by key (used by clickable dashboard cards)."""
        idx = self._pages.get(key)
        if idx is None:
            return
        self.stack.setCurrentIndex(idx)
        btn = self._nav_buttons.get(key)
        if btn is not None:
            btn.setChecked(True)

    def _on_settings_saved(self) -> None:
        """Reflect a shop-name change live (title, sidebar brand, status bar)."""
        company = self.ctx.company.get_company()
        shop_name = company.get("shop_name") or "Penguix"
        self.setWindowTitle(f"{shop_name} — Penguix")
        self.brand.setText(shop_name)
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
