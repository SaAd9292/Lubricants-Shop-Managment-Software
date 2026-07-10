"""Products page: searchable, filterable, sortable, paginated catalog.

Search and sort run server-side (in SQLite) so they stay correct across
pages and fast on large catalogs. Low-stock rows are tinted. Double-click a
row to edit; the toolbar adds / edits / adjusts stock / removes / restores.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.product_controller import ProductController
from .product_edit_dialog import ProductEditDialog
from .stock_adjust_dialog import StockAdjustDialog

PAGE_SIZE = 25

# (header label, sort key, is_money, is_numeric)
COLUMNS = [
    ("Barcode", "barcode", False, False),
    ("Name", "name", False, False),
    ("Brand", "brand", False, False),
    ("Category", "category", False, False),
    ("Unit", None, False, False),
    ("Purchase", "purchase_price", True, True),
    ("Sale", "sale_price", True, True),
    ("Stock", "stock", False, True),
    ("Min", None, False, True),
    ("Status", None, False, False),
]
_LOW_STOCK_TINT = QColor(180, 60, 60, 60)


class ProductsView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = ProductController(ctx)
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

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Products")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add Product")
        add_btn.clicked.connect(self._add)
        header.addWidget(add_btn)
        root.addLayout(header)

        # filter bar
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search or scan a barcode…")
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.search.returnPressed.connect(self._on_scan)
        self.search.setClearButtonEnabled(True)

        self.f_category = QComboBox()
        self.f_brand = QComboBox()
        self._fill_filter(self.f_category, "All categories", self.controller.categories())
        self._fill_filter(self.f_brand, "All brands", self.controller.brands())
        self.f_category.currentIndexChanged.connect(self._reset_and_reload)
        self.f_brand.currentIndexChanged.connect(self._reset_and_reload)

        self.f_low = QCheckBox("Low stock only")
        self.f_low.stateChanged.connect(self._reset_and_reload)
        self.f_inactive = QCheckBox("Show inactive")
        self.f_inactive.stateChanged.connect(self._reset_and_reload)
        self.f_inactive.stateChanged.connect(self._sync_action_label)

        filters.addWidget(self.search, 2)
        filters.addWidget(self.f_category, 1)
        filters.addWidget(self.f_brand, 1)
        filters.addWidget(self.f_low)
        filters.addWidget(self.f_inactive)
        root.addLayout(filters)

        # table
        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = 'No products yet - click "+ Add Product" to begin.'
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._on_sort)
        self.table.doubleClicked.connect(lambda: self._edit_selected())
        root.addWidget(self.table, 1)

        # footer: actions + pagination
        footer = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("Secondary")
        edit_btn.clicked.connect(self._edit_selected)
        adjust_btn = QPushButton("Adjust stock")
        adjust_btn.setObjectName("Secondary")
        adjust_btn.clicked.connect(self._adjust_selected)
        self.del_btn = QPushButton("Deactivate")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.clicked.connect(self._delete_selected)
        footer.addWidget(edit_btn)
        footer.addWidget(adjust_btn)
        footer.addWidget(self.del_btn)
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

    def _fill_filter(self, combo: QComboBox, all_label: str, items: list[dict]) -> None:
        combo.clear()
        combo.addItem(all_label, None)
        for it in items:
            combo.addItem(it["name"], it["id"])

    # -- data ---------------------------------------------------------
    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        result = self.controller.list(
            search=self.search.text(),
            category_id=self.f_category.currentData(),
            brand_id=self.f_brand.currentData(),
            only_active=not self.f_inactive.isChecked(),
            low_stock_only=self.f_low.isChecked(),
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
        for r, p in enumerate(rows):
            low = p["stock_qty"] <= p["min_stock_level"]
            values = [
                p.get("barcode") or "",
                p["name"],
                p.get("brand_name") or "",
                p.get("category_name") or "",
                p.get("unit_type") or "",
                self.controller.fmt(p["purchase_price_minor"]),
                self.controller.fmt(p["sale_price_minor"]),
                str(p["stock_qty"]),
                str(p["min_stock_level"]),
                "Active" if p["is_active"] else "Inactive",
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c in (5, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, p["id"])  # stash product id
                if low and p["is_active"]:
                    item.setBackground(_LOW_STOCK_TINT)
                self.table.setItem(r, c, item)

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(
            f"Page {self._page + 1} of {pages}   ({self._total} items)"
        )
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page + 1 < pages)

    # -- pagination ---------------------------------------------------
    def _prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._reload()

    def _next(self) -> None:
        if (self._page + 1) * PAGE_SIZE < self._total:
            self._page += 1
            self._reload()

    # -- sorting ------------------------------------------------------
    def _on_sort(self, col: int) -> None:
        key = COLUMNS[col][1]
        if not key:
            return
        if self._sort_by == key:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_by = key
            self._sort_dir = "asc"
        self._page = 0
        self._reload()

    # -- row helpers --------------------------------------------------
    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    # -- actions ------------------------------------------------------
    def _add(self) -> None:
        dlg = ProductEditDialog(self.controller)
        if dlg.exec():
            self._refresh_filters_and_reload()

    def _on_scan(self) -> None:
        """Enter/scan in the search box: if the barcode is a known product just
        select it; if it's new, offer to add it with the barcode pre-filled."""
        term = self.search.text().strip()
        if not term:
            return
        if self.controller.find_by_barcode(term):
            if self.table.rowCount() > 0:  # filter already narrowed to it
                self.table.selectRow(0)
            return
        ask = QMessageBox.question(
            self, "Add new product",
            f"No product has barcode '{term}'.\nAdd it as a new product?")
        if ask != QMessageBox.Yes:
            return
        dlg = ProductEditDialog(self.controller, prefill_barcode=term)
        if dlg.exec():
            self.search.clear()
            self._refresh_filters_and_reload()

    def _edit_selected(self) -> None:
        pid = self._selected_id()
        if pid is None:
            QMessageBox.information(self, "Select a product", "Please select a row first.")
            return
        dlg = ProductEditDialog(self.controller, product_id=pid)
        if dlg.exec():
            self._reload()

    def _adjust_selected(self) -> None:
        pid = self._selected_id()
        if pid is None:
            QMessageBox.information(self, "Select a product", "Please select a row first.")
            return
        if StockAdjustDialog(self.controller, pid).exec():
            self._reload()

    def _delete_selected(self) -> None:
        pid = self._selected_id()
        if pid is None:
            QMessageBox.information(self, "Select a product", "Please select a row first.")
            return
        showing_inactive = self.f_inactive.isChecked()
        if showing_inactive:
            ok, msg, _ = self.controller.reactivate(pid)
        else:
            confirm = QMessageBox.question(
                self, "Deactivate product",
                "Deactivate this product? It will be hidden from the product "
                "list, search, and the POS, but its details and past sales "
                "history are kept. You can reactivate it anytime by ticking "
                "'Show inactive'.",
            )
            if confirm != QMessageBox.Yes:
                return
            ok, msg, _ = self.controller.delete(pid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)

    def _sync_action_label(self) -> None:
        """The deactivate button doubles as 'Activate' while viewing inactive
        products, so its label follows the 'Show inactive' toggle."""
        self.del_btn.setText("Activate" if self.f_inactive.isChecked() else "Deactivate")

    def _refresh_filters_and_reload(self) -> None:
        # a newly added product may introduce a new brand/category
        cur_cat, cur_brand = self.f_category.currentData(), self.f_brand.currentData()
        self.f_category.blockSignals(True)
        self.f_brand.blockSignals(True)
        self._fill_filter(self.f_category, "All categories", self.controller.categories())
        self._fill_filter(self.f_brand, "All brands", self.controller.brands())
        self._restore(self.f_category, cur_cat)
        self._restore(self.f_brand, cur_brand)
        self.f_category.blockSignals(False)
        self.f_brand.blockSignals(False)
        self._reload()

    @staticmethod
    def _restore(combo: QComboBox, data) -> None:
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
