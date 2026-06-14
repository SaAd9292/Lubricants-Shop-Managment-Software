"""Add / Edit product dialog.

Prices are entered as decimals (e.g. 1500.00) and converted to minor units by
the controller. Brands and categories can be added inline without leaving the
form.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..controllers.product_controller import ProductController

UNIT_TYPES = ["Piece", "Bottle", "Carton", "Litre", "Kg"]


class ProductEditDialog(QDialog):
    def __init__(self, controller: ProductController, product_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.product_id = product_id
        self._minor_units = controller.currency()[1]
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self.setWindowTitle("Edit Product" if product_id else "Add Product")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_lookups()
        if product_id:
            self._load_product()

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type manufacturer barcode (optional)")

        self.brand = QComboBox()
        self.category = QComboBox()
        brand_row = self._combo_with_add(self.brand, self._add_brand)
        cat_row = self._combo_with_add(self.category, self._add_category)

        self.unit_type = QComboBox()
        self.unit_type.addItems(UNIT_TYPES)

        self.purchase_price = self._money_spin()
        self.sale_price = self._money_spin()

        self.stock_qty = QSpinBox()
        self.stock_qty.setRange(0, 1_000_000)
        self.min_stock = QSpinBox()
        self.min_stock.setRange(0, 1_000_000)

        form.addRow("Name *", self.name)
        form.addRow("Barcode", self.barcode)
        form.addRow("Brand", brand_row)
        form.addRow("Category", cat_row)
        form.addRow("Unit type", self.unit_type)
        form.addRow("Purchase price", self.purchase_price)
        form.addRow("Sale price", self.sale_price)
        form.addRow("Stock qty", self.stock_qty)
        form.addRow("Min stock level", self.min_stock)
        root.addLayout(form)

        # actions
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
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
        return spin

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
        self.purchase_price.setValue(float(Decimal(p["purchase_price_minor"]) / self._minor_units))
        self.sale_price.setValue(float(Decimal(p["sale_price_minor"]) / self._minor_units))
        self.stock_qty.setValue(p["stock_qty"])
        self.min_stock.setValue(p["min_stock_level"])

    @staticmethod
    def _select_data(combo: QComboBox, data) -> None:
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    # -- save ---------------------------------------------------------
    def _save(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Required", "Product name is required.")
            return
        form: dict[str, Any] = {
            "name": self.name.text().strip(),
            "barcode": self.barcode.text().strip(),
            "brand_id": self.brand.currentData(),
            "category_id": self.category.currentData(),
            "unit_type": self.unit_type.currentText(),
            "purchase_price": self.purchase_price.value(),
            "sale_price": self.sale_price.value(),
            "stock_qty": self.stock_qty.value(),
            "min_stock_level": self.min_stock.value(),
        }
        success, msg, _ = self.controller.save(form, self.product_id)
        if success:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)
