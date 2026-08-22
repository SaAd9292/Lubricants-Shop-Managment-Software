"""Products page: searchable, filterable, sortable, paginated catalog.

Search and sort run server-side (in SQLite) so they stay correct across
pages and fast on large catalogs. Low-stock rows are tinted. Double-click a
row to edit; the toolbar adds / edits / adjusts stock / removes / restores.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.packs import fmt_packs
from ..ui.widgets import DataTable
from ..controllers.product_controller import ProductController
from ..reports.report_exporter import to_pdf, to_xlsx
from ..services.column_presets import ColumnPresetStore
from .column_select_dialog import ColumnSelectDialog
from .product_edit_dialog import ProductEditDialog
from .security_prompt import require_admin_password
from .stock_adjust_dialog import StockAdjustDialog

PAGE_SIZE = 25

# (header label, sort key, is_money, is_numeric)
COLUMNS = [
    ("Order", "sort_order", False, True),   # manual display order (editable)
    ("Barcode", "barcode", False, False),
    ("Brand", "brand", False, False),
    ("Category", "category", False, False),
    ("Name", "name", False, False),
    ("Pack", None, False, False),           # structured packing (mirrors a price list)
    ("Units/CTN", None, False, True),
    ("Series", None, False, False),
    ("Purchase", "purchase_price", True, True),
    ("Sale", "sale_price", True, True),
    ("Margin %", None, False, True),
    ("Stock", "stock", False, True),
    ("", None, False, False),          # per-row Save button (price-edit mode)
]
_LOW_STOCK_TINT = QColor(180, 60, 60, 60)


def _margin_text(cost_minor: int, sale_minor: int) -> str:
    """Margin % shown in the list, computed from the ACTUAL purchase + sale
    prices ((sale - cost) / cost) so a hand-priced product shows its real margin,
    not the stored markup. '—' when there is no cost to divide by."""
    if not cost_minor:
        return "—"
    return f"{(sale_minor - cost_minor) / cost_minor * 100:g} %"


class ProductsView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = ProductController(ctx)
        self._symbol, self._minor_units = self.controller.currency()
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self._edit_prices = False
        self._page = 0
        self._total = 0
        self._sort_by = "sort_order"   # products default to the shop's custom order
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
        excel_btn = QPushButton("Export Excel")
        excel_btn.setObjectName("Secondary")
        excel_btn.clicked.connect(lambda: self._export("xlsx"))
        print_btn = QPushButton("Print")
        print_btn.setObjectName("Secondary")
        print_btn.clicked.connect(lambda: self._export("pdf"))
        header.addWidget(excel_btn)
        header.addWidget(print_btn)
        self.edit_prices_btn = QPushButton("Update prices")
        self.edit_prices_btn.setObjectName("Secondary")
        self.edit_prices_btn.setCheckable(True)
        self.edit_prices_btn.toggled.connect(self._toggle_price_edit)
        header.addWidget(self.edit_prices_btn)
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
        self.f_barcode = QComboBox()
        self.f_barcode.addItem("All products", None)
        self.f_barcode.addItem("With barcode", "with")
        self.f_barcode.addItem("Without barcode", "without")
        self.f_barcode.currentIndexChanged.connect(self._reset_and_reload)

        self.f_low = QCheckBox("Low stock only")
        self.f_low.stateChanged.connect(self._reset_and_reload)
        self.f_inactive = QCheckBox("Inactive only")
        self.f_inactive.stateChanged.connect(self._reset_and_reload)
        self.f_inactive.stateChanged.connect(self._sync_action_label)

        filters.addWidget(self.search, 2)
        filters.addWidget(self.f_category, 1)
        filters.addWidget(self.f_brand, 1)
        filters.addWidget(self.f_barcode, 1)
        filters.addWidget(self.f_low)
        filters.addWidget(self.f_inactive)
        root.addLayout(filters)

        # table
        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = 'No products yet - click "+ Add Product" to begin.'
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.setColumnHidden(len(COLUMNS) - 1, True)  # Save col: only in edit mode
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        # Fixed, user-resizable widths for EVERY column so the layout keeps the
        # same structure on any screen (Name never collapses). On a narrow laptop
        # the table simply scrolls horizontally instead of squeezing columns.
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setMinimumSectionSize(45)
        # Order Barcode Brand Categ Name Pack Units Series Purch Sale Margin Stock Save
        self._col_widths = [60, 130, 100, 130, 240, 70, 75, 110, 95, 95, 80, 110, 90]
        for _c, _w in enumerate(self._col_widths):
            self.table.setColumnWidth(_c, _w)
        hdr.sectionClicked.connect(self._on_sort)
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
        # Permanent delete — only shown while viewing inactive products.
        self.hard_del_btn = QPushButton("Delete permanently")
        self.hard_del_btn.setObjectName("Danger")
        self.hard_del_btn.clicked.connect(self._hard_delete_selected)
        self.hard_del_btn.setVisible(False)
        footer.addWidget(edit_btn)
        footer.addWidget(adjust_btn)
        footer.addWidget(self.del_btn)
        footer.addWidget(self.hard_del_btn)
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

    _NAME_COL = 4
    _NAME_MIN = 240

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt signature)
        super().resizeEvent(e)
        self._fit_name_column()

    def _fit_name_column(self) -> None:
        """Keep every column at its fixed width, but let the Name column grow to
        fill any leftover space on a wide screen (so there's no empty band on the
        right). On a narrow laptop Name stays at its minimum and the table scrolls
        — structure is identical on every screen."""
        table = getattr(self, "table", None)
        if table is None:
            return
        used = 0
        for c in range(table.columnCount()):
            if c == self._NAME_COL or table.isColumnHidden(c):
                continue
            used += table.columnWidth(c)
        avail = table.viewport().width()
        table.setColumnWidth(self._NAME_COL, max(self._NAME_MIN, avail - used))

    def _export(self, fmt: str) -> None:
        """Export the CURRENT product list (respecting search + all filters) to
        Excel, or open a PDF to print. Not limited to the visible page."""
        res = self.controller.list(
            search=self.search.text(),
            category_id=self.f_category.currentData(),
            brand_id=self.f_brand.currentData(),
            only_active=not self.f_inactive.isChecked(),
            inactive_only=self.f_inactive.isChecked(),
            low_stock_only=self.f_low.isChecked(),
            has_barcode=self.f_barcode.currentData(),
            sort_by=self._sort_by, sort_dir=self._sort_dir,
            limit=1_000_000, offset=0)
        products = res["rows"]
        if not products:
            QMessageBox.information(self, "Nothing to export",
                                    "No products match the current filters.")
            return
        columns = [
            {"key": "num", "label": "#", "align": "right"},
            {"key": "barcode", "label": "Barcode"},
            {"key": "name", "label": "Name"},
            {"key": "brand", "label": "Brand"},
            {"key": "category", "label": "Category"},
            {"key": "series", "label": "Series"},
            {"key": "pack_size", "label": "Pack"},
            {"key": "units_per_carton", "label": "Units/CTN", "align": "right"},
            {"key": "purchase", "label": "Purchase", "align": "right", "money": True},
            {"key": "sale", "label": "Sale", "align": "right", "money": True},
        ]
        rows = [{
            "num": p.get("sort_order") or 0,
            "barcode": p.get("barcode") or "",
            "name": p["name"],
            "brand": p.get("brand_name") or "",
            "category": p.get("category_name") or "",
            "series": p.get("series") or "",
            "pack_size": p.get("pack_size") or "",
            "units_per_carton": p.get("units_per_carton") or 1,
            "purchase": p["purchase_price_minor"],
            "sale": p["sale_price_minor"],
        } for p in products]
        # let the user tick exactly which columns to include (with presets)
        chosen = ColumnSelectDialog.pick(
            self, columns, "products", ColumnPresetStore(self.ctx.config.data_root))
        if chosen is None:
            return   # cancelled
        columns = [c for c in columns if c["key"] in chosen]

        company = self.ctx.company.get_company()
        scope = "Inactive" if self.f_inactive.isChecked() else "Active"
        report = {"key": "products", "title": "Product List",
                  "subtitle": f"{scope} · {len(products)} item(s)",
                  "columns": columns, "rows": rows}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            if fmt == "xlsx":
                suggested = str(Path.home() / f"products_{stamp}.xlsx")
                chosen, _ = QFileDialog.getSaveFileName(
                    self, "Save products as", suggested, "Excel files (*.xlsx)")
                if not chosen:
                    return
                path = to_xlsx(report, company, chosen)
                QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            else:  # pdf -> open for printing
                path = to_pdf(report, company, os.path.join(
                    tempfile.gettempdir(), f"products_{stamp}.pdf"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

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
            inactive_only=self.f_inactive.isChecked(),
            low_stock_only=self.f_low.isChecked(),
            has_barcode=self.f_barcode.currentData(),
            sort_by=self._sort_by,
            sort_dir=self._sort_dir,
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
        )
        self._total = result["total"]
        self._populate(result["rows"])
        self._update_pagination()
        # re-fit the Name column after rows render (scrollbar presence can change
        # the usable width); deferred so the table has its final size
        QTimer.singleShot(0, self._fit_name_column)

    def _populate(self, rows: list[dict]) -> None:
        # Rebuild from scratch so any edit-mode cell widgets from a previous
        # render are destroyed with their rows (setItem won't remove a widget).
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            low = p["min_stock_level"] > 0 and p["stock_qty"] <= p["min_stock_level"]
            values = [
                str(p.get("sort_order") or 0),
                p.get("barcode") or "",
                p.get("brand_name") or "",
                p.get("category_name") or "",
                p["name"],
                p.get("pack_size") or "",
                str(p.get("units_per_carton") or 1),
                p.get("series") or "",
                self.controller.fmt(p["purchase_price_minor"]),
                self.controller.fmt(p["sale_price_minor"]),
                _margin_text(p["purchase_price_minor"], p["sale_price_minor"]),
                fmt_packs(p["stock_qty"], p.get("units_per_carton")),
                "",  # Save (used only in price-edit mode)
            ]
            if self._edit_prices:
                # editors replace the Order/Purchase/Sale/Margin cells, so blank
                # the underlying text or it shows faded behind the editor.
                values[0] = values[8] = values[9] = values[10] = ""
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c in (0, 6, 8, 9, 10, 11):   # Order + Units/CTN + money/qty, right-aligned
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, p["id"])  # stash product id
                if low and p["is_active"]:
                    item.setBackground(_LOW_STOCK_TINT)
                self.table.setItem(r, c, item)
            if self._edit_prices:
                self._add_price_editors(r, p)

    # -- inline price editing -----------------------------------------
    def _toggle_price_edit(self, on: bool) -> None:
        """'Update prices' mode: swap the Purchase/Sale cells for editable spin
        boxes and show a per-row Save button (one product saved at a time)."""
        self._edit_prices = on
        self.edit_prices_btn.setText("Done editing prices" if on else "Update prices")
        self.table.setColumnHidden(len(COLUMNS) - 1, not on)
        self._reload()

    def _price_spin(self, minor: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1_000_000_000)
        spin.setDecimals(self._decimals)
        spin.setGroupSeparatorShown(True)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setValue(int(minor or 0) / self._minor_units)
        return spin

    def _add_price_editors(self, r: int, p: dict) -> None:
        # editable Order # so the owner can renumber a row to match the price
        # sheet during the same pass they update prices
        order = QSpinBox()
        order.setRange(0, 1_000_000_000)
        order.setButtonSymbols(QAbstractSpinBox.NoButtons)
        order.setValue(int(p.get("sort_order") or 0))
        self.table.setCellWidget(r, 0, order)

        ps = self._price_spin(p["purchase_price_minor"])
        ss = self._price_spin(p["sale_price_minor"])
        ms = QDoubleSpinBox()
        ms.setRange(0, 100000)
        ms.setDecimals(2)
        ms.setSuffix(" %")
        ms.setButtonSymbols(QAbstractSpinBox.NoButtons)
        ms.setValue((p.get("markup_bps") or 0) / 100.0)

        def _apply_margin():
            # markup > 0 -> derive the sale price from cost (rounded to the
            # nearest whole unit) and lock it; 0 % = manual sale price.
            m = ms.value()
            if m > 0:
                ss.blockSignals(True)
                ss.setValue(round(ps.value() * (1 + m / 100.0)))
                ss.blockSignals(False)
                ss.setReadOnly(True)
            else:
                ss.setReadOnly(False)

        ps.valueChanged.connect(_apply_margin)
        ms.valueChanged.connect(_apply_margin)
        _apply_margin()

        self.table.setCellWidget(r, 8, ps)
        self.table.setCellWidget(r, 9, ss)
        self.table.setCellWidget(r, 10, ms)
        btn = QPushButton("Save")
        btn.setObjectName("SuccessOutline")
        btn.clicked.connect(
            lambda _=False, pid=p["id"], o=order, a=ps, b=ss, c=ms, bt=btn:
            self._save_price(pid, o, a, b, c, bt))
        self.table.setCellWidget(r, len(COLUMNS) - 1, btn)

    def _save_price(self, pid, ospin, pspin, sspin, mspin, btn) -> None:
        ok, msg, _ = self.controller.save(
            {"sort_order": int(ospin.value()), "purchase_price": pspin.value(),
             "sale_price": sspin.value(), "markup": mspin.value()}, pid)
        if ok:
            btn.setText("Saved ✓")
            QTimer.singleShot(1400, lambda: btn.setText("Save"))
        else:
            QMessageBox.warning(self, "Could not update price", msg)

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
                "'Inactive only'.",
            )
            if confirm != QMessageBox.Yes:
                return
            ok, msg, _ = self.controller.delete(pid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)

    def _hard_delete_selected(self) -> None:
        pid = self._selected_id()
        if pid is None:
            QMessageBox.information(self, "Select a product", "Please select a row first.")
            return
        confirm = QMessageBox.warning(
            self, "Delete permanently",
            "Permanently delete this product? This cannot be undone.\n\n"
            "Only products with no purchase or sales history can be deleted; "
            "anything with history should stay deactivated instead.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        if not require_admin_password(self, self.ctx):
            return
        ok, msg, _ = self.controller.hard_delete(pid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)

    def _sync_action_label(self) -> None:
        """The deactivate button doubles as 'Activate' while viewing inactive
        products, so its label follows the 'Inactive only' toggle. Permanent
        delete is only offered there (you must deactivate a product first)."""
        inactive = self.f_inactive.isChecked()
        self.del_btn.setText("Activate" if inactive else "Deactivate")
        self.hard_del_btn.setVisible(inactive)

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
