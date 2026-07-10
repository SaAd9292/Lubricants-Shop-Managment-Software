"""Audit Log viewer (admin): read-only trail of who did what, when.

The audit_logs table is append-only; this screen just reads it with a text
search, an action filter, and pagination. Useful for supervising data entry.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable

PAGE_SIZE = 50
COLUMNS = ["When", "User", "Action", "Item", "Details"]


def _fmt_details(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return str(raw)
    if isinstance(data, dict):
        return ", ".join(f"{k}: {v}" for k, v in data.items())
    return str(data)


class AuditView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.audit = ctx.audit
        self._page = 0
        self._total = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reset_and_reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel("Audit Log")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search user, action, or item…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_action = QComboBox()
        self.f_action.addItem("All actions", None)
        for a in self.audit.distinct_actions():
            self.f_action.addItem(a, a)
        self.f_action.currentIndexChanged.connect(self._reset_and_reload)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_action)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = "No activity recorded yet."
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        for i in range(4):  # When / User / Action / Item size to content...
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)  # ...Details takes the rest
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.prev_btn = self._nav_btn("‹ Prev", self._prev)
        self.page_label = QLabel("")
        self.page_label.setObjectName("Muted")
        self.next_btn = self._nav_btn("Next ›", self._next)
        footer.addWidget(self.prev_btn)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)

    def _nav_btn(self, text, slot):
        from PySide6.QtWidgets import QPushButton
        b = QPushButton(text)
        b.setObjectName("Secondary")
        b.clicked.connect(slot)
        return b

    # -- data ---------------------------------------------------------
    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        result = self.audit.list_logs(
            search=self.search.text(), action=self.f_action.currentData(),
            limit=PAGE_SIZE, offset=self._page * PAGE_SIZE)
        self._total = result["total"]
        rows = result["rows"]
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            entity = a.get("entity_type") or ""
            if a.get("entity_id"):
                entity = f"{entity} #{a['entity_id']}"
            values = [
                (a.get("created_at") or "")[:19],
                a.get("who") or "—",
                a.get("action") or "",
                entity,
                _fmt_details(a.get("details")),
            ]
            for c, val in enumerate(values):
                from PySide6.QtWidgets import QTableWidgetItem
                self.table.setItem(r, c, QTableWidgetItem(val))
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} entries)")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page + 1 < pages)

    def _prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._reload()

    def _next(self) -> None:
        if (self._page + 1) * PAGE_SIZE < self._total:
            self._page += 1
            self._reload()
