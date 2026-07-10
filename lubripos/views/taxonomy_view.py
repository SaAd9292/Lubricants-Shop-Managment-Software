"""Categories & Brands management page (admin).

Two side-by-side panels. Each lists items with their product count and status,
and supports Add, Rename, and Activate/Deactivate. Items in use by products are
deactivated (soft) rather than deleted, preserving history.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.taxonomy_controller import TaxonomyController

COLUMNS = ["Name", "Products", "Status"]


class _Panel(QWidget):
    def __init__(self, controller: TaxonomyController, table: str, title: str) -> None:
        super().__init__()
        self.controller = controller
        self.table_key = table
        self._build_ui(title)
        self.reload()

    def _build_ui(self, title: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet("font-size: 16px; font-weight: 700;")
        header.addWidget(t)
        header.addStretch(1)
        self.show_inactive = QCheckBox("Show inactive")
        self.show_inactive.stateChanged.connect(self.reload)
        header.addWidget(self.show_inactive)
        root.addLayout(header)

        # add row
        add_row = QHBoxLayout()
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText(f"New {(title[:-3] + 'y' if title.lower().endswith('ies') else title[:-1]).lower()} name…")
        self.new_name.returnPressed.connect(self._add)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add)
        add_row.addWidget(self.new_name, 1)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = f"No {title.lower()} yet."
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._rename)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("Secondary")
        rename_btn.clicked.connect(self._rename)
        self.toggle_btn = QPushButton("Activate / Deactivate")
        self.toggle_btn.setObjectName("Secondary")
        self.toggle_btn.clicked.connect(self._toggle)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("Secondary")
        del_btn.clicked.connect(self._delete)
        actions.addWidget(rename_btn)
        actions.addWidget(self.toggle_btn)
        actions.addWidget(del_btn)
        actions.addStretch(1)
        root.addLayout(actions)

    def reload(self) -> None:
        rows = self.controller.list(self.table_key,
                                    active_only=not self.show_inactive.isChecked())
        self.table.setRowCount(len(rows))
        for r, it in enumerate(rows):
            values = [it["name"], str(it.get("product_count", 0)),
                      "Active" if it["is_active"] else "Inactive"]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 1:
                    item.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    item.setData(Qt.UserRole, it["id"])
                    item.setData(Qt.UserRole + 1, bool(it["is_active"]))
                    item.setData(Qt.UserRole + 2, it.get("product_count", 0))
                if not it["is_active"]:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None, None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole), item.text(), item.data(Qt.UserRole + 1)

    def _add(self) -> None:
        name = self.new_name.text().strip()
        if not name:
            return
        ok, msg, _ = self.controller.add(self.table_key, name)
        if ok:
            self.new_name.clear()
            self.reload()
        else:
            QMessageBox.warning(self, "Could not add", msg)

    def _rename(self) -> None:
        item_id, current, _ = self._selected()
        if item_id is None:
            QMessageBox.information(self, "Select an item", "Please select a row first.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:",
                                            QLineEdit.Normal, current)
        if not ok or not new_name.strip():
            return
        success, msg, _ = self.controller.rename(self.table_key, item_id, new_name.strip())
        if success:
            self.reload()
        else:
            QMessageBox.warning(self, "Could not rename", msg)

    def _delete(self) -> None:
        item_id, name, _ = self._selected()
        if item_id is None:
            QMessageBox.information(self, "Select an item", "Please select a row first.")
            return
        count = self.table.item(self.table.currentRow(), 0).data(Qt.UserRole + 2) or 0
        noun = (self.table_key[:-3] + 'y' if self.table_key.endswith('ies') else self.table_key[:-1])
        warn = (f"\n\n{count} product(s) currently use it. They will be left with "
                f"no {noun}.") if count else ""
        confirm = QMessageBox.warning(
            self, "Delete permanently",
            f"Permanently delete '{name}'?{warn}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.delete(self.table_key, item_id)
        if ok:
            self.reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)

    def _toggle(self) -> None:
        item_id, _, active = self._selected()
        if item_id is None:
            QMessageBox.information(self, "Select an item", "Please select a row first.")
            return
        success, msg, _ = self.controller.set_active(self.table_key, item_id, not active)
        if success:
            self.reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)


class TaxonomyView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.controller = TaxonomyController(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(16)

        title = QLabel("Categories & Brands")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        panels = QHBoxLayout()
        panels.setSpacing(24)
        panels.addWidget(_Panel(self.controller, "categories", "Categories"))
        panels.addWidget(_Panel(self.controller, "brands", "Brands"))
        root.addLayout(panels, 1)
