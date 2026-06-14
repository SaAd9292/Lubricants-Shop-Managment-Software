"""Reusable product picker: search and select a single product.

Used by the purchase dialog (and later the POS) to pick a product by name or
barcode. Returns the selected product dict via `.selected`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHeaderView, QLineEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)


class ProductPickerDialog(QDialog):
    def __init__(self, search_fn, fmt_fn) -> None:
        """search_fn(term)->list[dict]; fmt_fn(minor)->str."""
        super().__init__()
        self._search_fn = search_fn
        self._fmt = fmt_fn
        self.selected: dict | None = None
        self.setWindowTitle("Select product")
        self.setMinimumSize(560, 420)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or barcode…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        root.addWidget(self.search)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Barcode", "Stock", "Sale price"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._choose)
        root.addWidget(self.table, 1)
        self.search.setFocus()

    def _reload(self) -> None:
        rows = self._search_fn(self.search.text())
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            cells = [p["name"], p.get("barcode") or "", str(p["stock_qty"]),
                     self._fmt(p["sale_price_minor"])]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, p)
                self.table.setItem(r, c, item)

    def _choose(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.selected = self.table.item(row, 0).data(Qt.UserRole)
        self.accept()
