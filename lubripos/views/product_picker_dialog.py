"""Reusable product picker: search and select a single product.

Used by the POS ('Search product') and the purchase dialog to pick a product by
name or barcode, optionally narrowed to a category. Returns the selected product
dict via `.selected`.

Backward compatible: pass `categories` (a list of {id,name}) to show the category
dropdown; when given, the search function is called as search_fn(term, category_id),
otherwise as search_fn(term).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class ProductPickerDialog(QDialog):
    def __init__(self, search_fn, fmt_fn, categories=None, allow_carton=False) -> None:
        """search_fn(term[, category_id]) -> list[dict]; fmt_fn(minor) -> str.
        categories: optional list of {id, name} to enable the category filter.
        allow_carton: POS mode — shows Units/CTN and an 'Add carton' action that
        sells a whole carton (units_per_carton bottles) at the per-bottle price.
        The chosen quantity is returned in `.add_qty` (1 for a single bottle)."""
        super().__init__()
        self._search_fn = search_fn
        self._fmt = fmt_fn
        self._categories = categories
        self._allow_carton = allow_carton
        self.selected: dict | None = None
        self.add_qty: int = 1
        self.setWindowTitle("Select product")
        self.setMinimumSize(600, 440)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or barcode…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        top.addWidget(self.search, 1)

        self.f_cat = None
        if self._categories is not None:
            self.f_cat = QComboBox()
            self.f_cat.addItem("All categories", None)
            for c in self._categories:
                self.f_cat.addItem(c["name"], c["id"])
            self.f_cat.currentIndexChanged.connect(self._reload)
            top.addWidget(self.f_cat)
        root.addLayout(top)

        headers = ["Name", "Barcode", "Stock", "Sale price"]
        if self._allow_carton:
            headers.append("Units/CTN")
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        # Double-click = add a single bottle (fast common case).
        self.table.doubleClicked.connect(lambda *_: self._choose(carton=False))
        root.addWidget(self.table, 1)

        if self._allow_carton:
            actions = QHBoxLayout()
            actions.addStretch(1)
            self.btn_bottle = QPushButton("Add bottle")
            self.btn_bottle.setObjectName("Secondary")
            self.btn_bottle.clicked.connect(lambda: self._choose(carton=False))
            self.btn_carton = QPushButton("Add carton")
            self.btn_carton.clicked.connect(lambda: self._choose(carton=True))
            self.btn_carton.setEnabled(False)
            actions.addWidget(self.btn_bottle)
            actions.addWidget(self.btn_carton)
            root.addLayout(actions)
            self.table.itemSelectionChanged.connect(self._update_carton_btn)

        self.search.setFocus()

    def _update_carton_btn(self) -> None:
        """Enable 'Add carton' only for products that come in cartons (>1/ctn),
        and show the pack size on the button so the cashier sees what a carton is."""
        p = self._current_product()
        upc = int((p or {}).get("units_per_carton") or 1)
        self.btn_carton.setEnabled(p is not None and upc > 1)
        self.btn_carton.setText(f"Add carton (×{upc})" if upc > 1 else "Add carton")

    def _reload(self) -> None:
        term = self.search.text()
        if self.f_cat is not None:
            rows = self._search_fn(term, self.f_cat.currentData())
        else:
            rows = self._search_fn(term)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            cells = [p["name"], p.get("barcode") or "", str(p["stock_qty"]),
                     self._fmt(p["sale_price_minor"])]
            if self._allow_carton:
                upc = int(p.get("units_per_carton") or 1)
                cells.append(f"{upc}" if upc > 1 else "—")
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, p)
                self.table.setItem(r, c, item)
        if self._allow_carton:
            self._update_carton_btn()

    def _current_product(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _choose(self, carton: bool = False) -> None:
        p = self._current_product()
        if p is None:
            return
        self.selected = p
        self.add_qty = int(p.get("units_per_carton") or 1) if carton else 1
        self.accept()
