"""Expenses page: filterable, paginated table with running total."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.expense_controller import ExpenseController
from .expense_edit_dialog import ExpenseEditDialog

PAGE_SIZE = 25
COLUMNS = ["Date", "Category", "Amount", "Description", "By"]


class ExpensesView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = ExpenseController(ctx)
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

        header = QHBoxLayout()
        title = QLabel("Expenses")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add Expense")
        add_btn.clicked.connect(self._add)
        header.addWidget(add_btn)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search description…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_category = QComboBox()
        self._fill_categories()
        self.f_category.currentIndexChanged.connect(self._reset_and_reload)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_category)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = 'No expenses yet - click "+ Add Expense" to begin.'
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda: self._edit_selected())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("Secondary")
        edit_btn.clicked.connect(self._edit_selected)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("Secondary")
        del_btn.clicked.connect(self._delete_selected)
        footer.addWidget(edit_btn)
        footer.addWidget(del_btn)
        self.sum_label = QLabel("")
        self.sum_label.setStyleSheet("font-weight:700;")
        footer.addSpacing(16)
        footer.addWidget(self.sum_label)
        footer.addStretch(1)
        self.prev_btn = QPushButton("‹ Prev")
        self.prev_btn.setObjectName("Secondary")
        self.prev_btn.clicked.connect(self._prev)
        self.page_label = QLabel("")
        self.page_label.setObjectName("Muted")
        self.next_btn = QPushButton("Next ›")
        self.next_btn.setObjectName("Secondary")
        self.next_btn.clicked.connect(self._next)
        footer.addWidget(self.prev_btn)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)

    def _fill_categories(self) -> None:
        self.f_category.clear()
        self.f_category.addItem("All categories", None)
        for c in self.controller.categories():
            self.f_category.addItem(c["name"], c["name"])

    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        result = self.controller.list(
            search=self.search.text(),
            category=self.f_category.currentData(),
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
        )
        self._total = result["total"]
        self._populate(result["rows"])
        self.sum_label.setText("Filtered total: " + self.controller.fmt(result["sum_minor"]))
        self._update_pagination()

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            values = [
                (e.get("expense_date") or "")[:10], e.get("category") or "",
                self.controller.fmt(e["amount_minor"]), e.get("description") or "",
                e.get("created_by_name") or "-",
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, e["id"])
                self.table.setItem(r, c, item)

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} expenses)")
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

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _add(self) -> None:
        if ExpenseEditDialog(self.controller).exec():
            self._refresh_filter_and_reload()

    def _edit_selected(self) -> None:
        eid = self._selected_id()
        if eid is None:
            QMessageBox.information(self, "Select an expense", "Please select a row first.")
            return
        if ExpenseEditDialog(self.controller, expense_id=eid).exec():
            self._reload()

    def _delete_selected(self) -> None:
        eid = self._selected_id()
        if eid is None:
            QMessageBox.information(self, "Select an expense", "Please select a row first.")
            return
        confirm = QMessageBox.question(self, "Delete expense", "Delete this expense permanently?")
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.delete(eid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)

    def _refresh_filter_and_reload(self) -> None:
        cur = self.f_category.currentData()
        self.f_category.blockSignals(True)
        self._fill_categories()
        idx = self.f_category.findData(cur)
        self.f_category.setCurrentIndex(idx if idx >= 0 else 0)
        self.f_category.blockSignals(False)
        self._reload()
