"""Admin Panel: one home for every administrator-only screen.

Folds Back-date Entry, Users, Audit Log, Backup & Restore and Settings into a
single tabbed page so the sidebar stays short and the sensitive tools sit
together behind one admin-only entry. Each tab reuses its existing view widget
unchanged — this is composition, not a rewrite. The tab's data is refreshed as
it becomes visible, matching how the sidebar refreshed each page on navigation.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ..app_context import AppContext
from ..core.i18n import tr
from .audit_view import AuditView
from .backup_view import BackupView
from .backdate_entry_view import BackdateEntryView
from .settings_view import SettingsView
from .users_view import UsersView


class AdminPanelView(QWidget):
    def __init__(self, ctx: AppContext, on_settings_saved=None,
                 on_check_updates=None) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.backdate = BackdateEntryView(ctx)
        self.users = UsersView(ctx)
        self.audit = AuditView(ctx)
        self.backup = BackupView(ctx)
        self.settings = SettingsView(ctx, on_saved=on_settings_saved,
                                     on_check_updates=on_check_updates)

        self.tabs.addTab(self.backdate, tr("Back-date Entry"))
        self.tabs.addTab(self.users, tr("Users"))
        self.tabs.addTab(self.audit, tr("Audit Log"))
        self.tabs.addTab(self.backup, tr("Backup & Restore"))
        self._settings_index = self.tabs.addTab(self.settings, tr("Settings"))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs)

    def _on_tab_changed(self, _index: int) -> None:
        self._refresh_current()

    def _refresh_current(self) -> None:
        """Re-pull the visible tab's data if it exposes a refresh hook. A refresh
        must never break the panel, so failures are swallowed."""
        widget = self.tabs.currentWidget()
        for name in ("refresh", "_reload"):
            fn = getattr(widget, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                return

    def _reload(self) -> None:
        """Nav hook used by MainWindow when the Admin Panel becomes visible."""
        self._refresh_current()

    def show_settings(self) -> None:
        """Jump to the Settings tab (used by the update banner's admin flow)."""
        self.tabs.setCurrentIndex(self._settings_index)
