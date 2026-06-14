"""Suppliers page: searchable, sortable, paginated table with soft delete."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.supplier_controller import SupplierController
from .supplier_edit_dialog import SupplierEditDialog

PAGE_SIZE = 25
# (label, sort key)
COLUMNS = [("Name", "name"), ("Phone", "phone"), ("Address", None),
           ("Notes", None), ("Status", None)]


class SuppliersView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SupplierController(ctx)
        self._page = 0
        self._total = 0
        self._sort_by = "name"
        self._sort_dir = "asc"
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Suppliers")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add Supplier")
        add_btn.clicked.connect(self._add)
        header.addWidget(add_btn)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, phone, or address…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_inactive = QCheckBox("Show inactive")
        self.f_inactive.stateChanged.connect(self._reset_and_reload)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_inactive)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = 'No suppliers yet - click "+ Add Supplier" to begin.'
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._on_sort)
        self.table.doubleClicked.connect(lambda: self._edit_selected())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("Secondary")
        edit_btn.clicked.connect(self._edit_selected)
        self.del_btn = QPushButton("Remove")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.clicked.connect(self._delete_selected)
        self.purge_btn = QPushButton("Delete")
        self.purge_btn.setObjectName("Secondary")
        self.purge_btn.clicked.connect(self._delete_permanent)
        footer.addWidget(edit_btn)
        footer.addWidget(self.del_btn)
        footer.addWidget(self.purge_btn)
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

    # -- data ---------------------------------------------------------
    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        result = self.controller.list(
            search=self.search.text(),
            only_active=not self.f_inactive.isChecked(),
            sort_by=self._sort_by,
            sort_dir=self._sort_dir,
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
        )
        self._total = result["total"]
        self._populate(result["rows"])
        self._update_pagination()

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            values = [
                s["name"], s.get("phone") or "", s.get("address") or "",
                s.get("notes") or "", "Active" if s["is_active"] else "Inactive",
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, s["id"])
                    item.setData(Qt.UserRole + 2, s.get("purchase_count", 0))
                self.table.setItem(r, c, item)

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} suppliers)")
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

    def _on_sort(self, col: int) -> None:
        key = COLUMNS[col][1]
        if not key:
            return
        if self._sort_by == key:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_by, self._sort_dir = key, "asc"
        self._page = 0
        self._reload()

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    # -- actions ------------------------------------------------------
    def _add(self) -> None:
        if SupplierEditDialog(self.controller).exec():
            self._reset_and_reload()

    def _edit_selected(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Select a supplier", "Please select a row first.")
            return
        if SupplierEditDialog(self.controller, supplier_id=sid).exec():
            self._reload()

    def _delete_selected(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Select a supplier", "Please select a row first.")
            return
        if self.f_inactive.isChecked():
            ok, msg, _ = self.controller.reactivate(sid)
        else:
            confirm = QMessageBox.question(
                self, "Remove supplier",
                "Remove this supplier? Purchase history is kept.",
            )
            if confirm != QMessageBox.Yes:
                return
            ok, msg, _ = self.controller.delete(sid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)

    def _delete_permanent(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Select a supplier", "Please select a row first.")
            return
        pc = self.table.item(self.table.currentRow(), 0).data(Qt.UserRole + 2) or 0
        warn = (f"\n\n{pc} purchase(s) reference this supplier. Those records are kept "
                f"but will show no supplier.") if pc else ""
        confirm = QMessageBox.warning(
            self, "Delete permanently",
            f"Permanently delete this supplier?{warn}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.hard_delete(sid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)
