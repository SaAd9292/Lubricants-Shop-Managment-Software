"""Add / Edit product dialog.

Prices are entered as decimals (e.g. 1500.00) and converted to minor units by
the controller. Brands and categories can be added inline without leaving the
form.

Fast-entry features for data-entry work:
  * Auto-focus the Name field; Enter saves (Save is the default button).
  * "Save && add another" keeps the form open and clears it for the next item.
  * Live duplicate-barcode warning as you type.
  * Remembers the last-used brand / category / unit / markup and pre-selects
    them on the next new product (module-level _LAST).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..controllers.product_controller import ProductController
from ..core.packs import name_with_pack, split_packs

UNIT_TYPES = ["Piece", "Bottle", "Carton", "Litre", "Kg"]

# Remembers the last-used selections across new-product dialogs in this session.
_LAST: dict[str, Any] = {"brand_id": None, "category_id": None,
                         "unit": "Piece", "markup": 0.0}


class ProductEditDialog(QDialog):
    def __init__(self, controller: ProductController, product_id: int | None = None,
                 prefill_barcode: str | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.product_id = product_id
        self._symbol, self._minor_units = controller.currency()
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self._saved_any = False
        self.setWindowTitle("Edit Product" if product_id else "Add Product")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_lookups()
        if product_id:
            self._load_product()
            self.name.setFocus()
        else:
            self._apply_last_used()
            if prefill_barcode:
                self.barcode.setText(prefill_barcode)
                self.name.setFocus()
            else:
                self.barcode.setFocus()  # ready to scan the barcode first

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type manufacturer barcode (optional)")
        self.barcode.textChanged.connect(self._check_barcode)
        # A scanner types the code then sends Enter. Move focus to Name on that
        # Enter (don't save yet); Enter from the Name field is what saves.
        self.barcode.returnPressed.connect(self.name.setFocus)
        self.name.returnPressed.connect(lambda: self._save())

        self.brand = QComboBox()
        self.category = QComboBox()
        brand_row = self._combo_with_add(self.brand, self._add_brand)
        cat_row = self._combo_with_add(self.category, self._add_category)

        self.unit_type = QComboBox()
        self.unit_type.addItems(UNIT_TYPES)

        # Structured packing (mirrors a manufacturer price list).
        self.series = QLineEdit()
        self.series.setPlaceholderText("e.g. Platinum, Gold (optional)")
        self.pack_size = QLineEdit()
        self.pack_size.setPlaceholderText("e.g. 1 L, 4 L (optional)")
        self.units_per_carton = QSpinBox()
        self.units_per_carton.setRange(1, 1000)
        self.units_per_carton.setValue(1)
        self.units_per_carton.setToolTip(
            "How many packs make a full carton — lets you sell a whole carton at POS.")

        self.purchase_price = self._money_spin()
        self.sale_price = self._money_spin()
        self.markup = QDoubleSpinBox()
        self.markup.setRange(0, 100000)
        self.markup.setDecimals(2)
        self.markup.setSuffix(" %")
        # When markup > 0 the sale price is derived from cost; recompute live.
        self.purchase_price.valueChanged.connect(self._recompute_sale)
        self.markup.valueChanged.connect(self._recompute_sale)
        # Live margin readout from the actual purchase + sale prices (works even
        # when the sale price is typed manually with markup left at 0).
        self.margin_lbl = QLabel("")
        self.margin_lbl.setStyleSheet("color:#0f766e; font-weight:600;")
        self.purchase_price.valueChanged.connect(self._update_margin)
        self.sale_price.valueChanged.connect(self._update_margin)

        # Opening stock entered as cartons + loose pieces (converted to a piece
        # count on save). The cartons box is enabled only when the product ships
        # in cartons (units per carton > 1).
        self.stock_cartons = QSpinBox()
        self.stock_cartons.setRange(0, 1_000_000)
        self.stock_cartons.setSuffix(" ctn")
        self.stock_pieces = QSpinBox()
        self.stock_pieces.setRange(0, 1_000_000)
        self.stock_pieces.setSuffix(" pc")
        stock_box = QWidget()
        _sh = QHBoxLayout(stock_box)
        _sh.setContentsMargins(0, 0, 0, 0)
        _sh.addWidget(self.stock_cartons)
        _sh.addWidget(self.stock_pieces)
        self.stock_hint = QLabel("")
        self.stock_hint.setStyleSheet("color:#64748b;")
        self.stock_cartons.valueChanged.connect(self._update_stock)
        self.stock_pieces.valueChanged.connect(self._update_stock)
        self.units_per_carton.valueChanged.connect(self._update_stock)
        self.min_stock = QSpinBox()
        self.min_stock.setRange(0, 1_000_000)

        self.name_preview = QLabel("")
        self.name_preview.setStyleSheet("color:#64748b; font-size:11px;")
        self.name.textChanged.connect(self._update_name_preview)
        self.pack_size.textChanged.connect(self._update_name_preview)

        form.addRow("Name *", self.name)
        form.addRow("", self.name_preview)
        form.addRow("Barcode", self.barcode)
        form.addRow("Brand", brand_row)
        form.addRow("Category", cat_row)
        form.addRow("Unit type", self.unit_type)
        form.addRow("Series", self.series)
        form.addRow("Pack size", self.pack_size)
        form.addRow("Units / carton", self.units_per_carton)
        form.addRow("Purchase price", self.purchase_price)
        form.addRow("Markup % (0 = manual)", self.markup)
        form.addRow("Sale price", self.sale_price)
        form.addRow("Margin", self.margin_lbl)
        form.addRow("Opening stock", stock_box)
        form.addRow("", self.stock_hint)
        form.addRow("Min stock level", self.min_stock)
        root.addLayout(form)
        self._update_stock()

        self.bc_warn = QLabel("")
        self.bc_warn.setStyleSheet("color: #b00020;")
        self.bc_warn.setVisible(False)
        root.addWidget(self.bc_warn)

        # actions
        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self._close)
        actions.addWidget(cancel)
        actions.addStretch(1)
        if self.product_id is None:
            add_more = QPushButton("Save && add another")
            add_more.setObjectName("Secondary")
            add_more.clicked.connect(lambda: self._save(add_another=True))
            actions.addWidget(add_more)
        save = QPushButton("Save")
        save.clicked.connect(lambda: self._save())
        actions.addWidget(save)
        root.addLayout(actions)

    def _combo_with_add(self, combo: QComboBox, on_add) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(combo, 1)
        btn = QPushButton("+")
        btn.setFixedWidth(36)
        btn.setObjectName("Secondary")
        btn.clicked.connect(on_add)
        lay.addWidget(btn)
        return w

    def _money_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1_000_000_000)
        spin.setDecimals(self._decimals)
        spin.setGroupSeparatorShown(True)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        return spin

    def _update_margin(self) -> None:
        """Show the live profit margin implied by the purchase + sale prices,
        regardless of whether markup was used or the sale price was typed by hand.
        (Margin % here = (sale - cost) / cost, matching the Products list column.)"""
        cost = self.purchase_price.value()
        sale = self.sale_price.value()
        if cost > 0 and sale > 0:
            pct = (sale - cost) / cost * 100
            profit = sale - cost
            self.margin_lbl.setText(
                f"{pct:.1f}%   ·   {self._symbol} {profit:,.{self._decimals}f} profit / unit")
        elif sale > 0 and cost <= 0:
            self.margin_lbl.setText("set a purchase price to see the margin")
        else:
            self.margin_lbl.setText("")

    def _update_name_preview(self) -> None:
        """Show the final saved name when the pack size will be appended."""
        typed = self.name.text().strip()
        final = name_with_pack(self.name.text(), self.pack_size.text())
        self.name_preview.setText(f"Saves as:  {final}" if typed and final != typed else "")

    def _stock_total(self) -> int:
        """Opening stock as a single piece count."""
        upc = self.units_per_carton.value()
        pieces = self.stock_pieces.value()
        return self.stock_cartons.value() * upc + pieces if upc > 1 else pieces

    def _update_stock(self) -> None:
        """Enable the cartons box only for carton products; show the total."""
        upc = self.units_per_carton.value()
        self.stock_cartons.setEnabled(upc > 1)
        if upc <= 1 and self.stock_cartons.value():
            self.stock_cartons.setValue(0)
        self.stock_hint.setText(f"= {self._stock_total()} pc total" if upc > 1 else "")

    def _recompute_sale(self) -> None:
        """If a markup is set, derive the sale price from cost (rounded to the
        nearest whole unit) and lock the field; markup 0 = manual price."""
        m = self.markup.value()
        if m > 0:
            sale = round(self.purchase_price.value() * (1 + m / 100.0))
            self.sale_price.setValue(sale)
            self.sale_price.setReadOnly(True)
        else:
            self.sale_price.setReadOnly(False)

    def _check_barcode(self, text: str) -> None:
        """Warn live if the typed barcode already belongs to another product."""
        found = self.controller.find_by_barcode(text)
        if found and found.get("id") != self.product_id:
            self.bc_warn.setText(f"⚠ Barcode already used by '{found['name']}'.")
            self.bc_warn.setVisible(True)
        else:
            self.bc_warn.setVisible(False)

    # -- lookups ------------------------------------------------------
    def _load_lookups(self) -> None:
        self.brand.clear()
        self.brand.addItem("— None —", None)
        for b in self.controller.brands():
            self.brand.addItem(b["name"], b["id"])
        self.category.clear()
        self.category.addItem("— None —", None)
        for c in self.controller.categories():
            self.category.addItem(c["name"], c["id"])

    def _apply_last_used(self) -> None:
        self._select_data(self.brand, _LAST.get("brand_id"))
        self._select_data(self.category, _LAST.get("category_id"))
        self.unit_type.setCurrentText(_LAST.get("unit") or "Piece")
        self.markup.setValue(float(_LAST.get("markup") or 0.0))

    def _add_brand(self) -> None:
        name, ok = QInputDialog.getText(self, "Add brand", "Brand name:")
        if ok and name.strip():
            success, msg, _ = self.controller.add_brand(name.strip())
            if success:
                self._load_lookups()
                self.brand.setCurrentText(name.strip())
            else:
                QMessageBox.warning(self, "Error", msg)

    def _add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "Add category", "Category name:")
        if ok and name.strip():
            success, msg, _ = self.controller.add_category(name.strip())
            if success:
                self._load_lookups()
                self.category.setCurrentText(name.strip())
            else:
                QMessageBox.warning(self, "Error", msg)

    # -- load existing ------------------------------------------------
    def _load_product(self) -> None:
        p = self.controller.get(self.product_id)
        self.name.setText(p["name"])
        self.barcode.setText(p.get("barcode") or "")
        self._select_data(self.brand, p.get("brand_id"))
        self._select_data(self.category, p.get("category_id"))
        self.unit_type.setCurrentText(p.get("unit_type") or "Piece")
        self.series.setText(p.get("series") or "")
        self.pack_size.setText(p.get("pack_size") or "")
        self.units_per_carton.setValue(int(p.get("units_per_carton") or 1))
        self.purchase_price.setValue(float(Decimal(p["purchase_price_minor"]) / self._minor_units))
        self.sale_price.setValue(float(Decimal(p["sale_price_minor"]) / self._minor_units))
        # Set markup last: if > 0 it re-derives & locks the sale price; if 0 the
        # stored sale price above stays as a manual value.
        self.markup.setValue((p.get("markup_bps") or 0) / 100.0)
        cartons, pieces = split_packs(p["stock_qty"], self.units_per_carton.value())
        self.stock_cartons.setValue(cartons)
        self.stock_pieces.setValue(pieces)
        self.min_stock.setValue(p["min_stock_level"])

    @staticmethod
    def _select_data(combo: QComboBox, data) -> None:
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    # -- save ---------------------------------------------------------
    def _save(self, add_another: bool = False) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Required", "Product name is required.")
            return
        pack = self.pack_size.text().strip()
        form: dict[str, Any] = {
            # pack size is folded into the name, e.g. "S-oil 0W-20" + "4L" ->
            # "S-oil 0W-20 4L" (idempotent — never doubles up on re-save).
            "name": name_with_pack(self.name.text(), pack),
            "barcode": self.barcode.text().strip(),
            "brand_id": self.brand.currentData(),
            "category_id": self.category.currentData(),
            "unit_type": self.unit_type.currentText(),
            "series": self.series.text().strip() or None,
            "pack_size": pack or None,
            "units_per_carton": self.units_per_carton.value(),
            "purchase_price": self.purchase_price.value(),
            "sale_price": self.sale_price.value(),
            "markup": self.markup.value(),
            "stock_qty": self._stock_total(),
            "min_stock_level": self.min_stock.value(),
        }
        success, msg, _ = self.controller.save(form, self.product_id)
        if not success:
            QMessageBox.warning(self, "Could not save", msg)
            return
        # remember selections to speed up the next new product
        _LAST.update(brand_id=self.brand.currentData(),
                     category_id=self.category.currentData(),
                     unit=self.unit_type.currentText(),
                     markup=self.markup.value())
        if add_another:
            self._saved_any = True
            self._clear_for_next()
        else:
            self.accept()

    def _clear_for_next(self) -> None:
        """Reset the per-item fields, keep brand/category/unit/markup/prices."""
        self.name.clear()
        self.barcode.clear()
        self.stock_cartons.setValue(0)
        self.stock_pieces.setValue(0)
        self.bc_warn.setVisible(False)
        self.barcode.setFocus()  # ready to scan the next item

    def _close(self) -> None:
        # If we added items via "Save && add another", report success so the
        # product list refreshes; otherwise it is a plain cancel.
        self.accept() if self._saved_any else self.reject()
