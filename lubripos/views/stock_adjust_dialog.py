"""Stock adjustment dialog: correct a product's on-hand quantity (stock-take).

This is a MANUAL override (not a purchase/sale), so it captures a reason and
writes a before/after entry to the audit log via the controller/service.

For products sold in cartons the count is entered as cartons + loose pieces —
the way stock is actually counted on the shelf — and converted to a single
piece count underneath.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout,
)

from ..controllers.product_controller import ProductController
from ..core.packs import fmt_packs
from ..ui.widgets import CartonQtyEntry

REASONS = ["Stock count correction", "Damaged", "Lost / theft",
           "Returned to supplier", "Expired", "Other"]


class StockAdjustDialog(QDialog):
    def __init__(self, controller: ProductController, product_id: int) -> None:
        super().__init__()
        self.controller = controller
        self.product_id = product_id
        self.product = controller.get(product_id)
        self.upc = max(1, int(self.product.get("units_per_carton") or 1))
        self.setWindowTitle("Adjust Stock")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)

        name = QLabel(self.product["name"])
        name.setStyleSheet("font-weight: 600;")
        current = QLabel(fmt_packs(self.product["stock_qty"], self.upc))
        form.addRow("Product", name)
        form.addRow("Current stock", current)

        self.qty = CartonQtyEntry(self.upc)
        self.qty.set_total(self.product["stock_qty"])
        label = f"New count ({self.upc}/ctn) *" if self.upc > 1 else "New counted qty *"
        form.addRow(label, self.qty)
        self.total_lbl = QLabel()
        self.total_lbl.setStyleSheet("color:#64748b;")
        if self.upc > 1:
            form.addRow("", self.total_lbl)
            self.qty.valueChanged.connect(self._update_total)
            self._update_total()

        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(REASONS)
        self.reason.setCurrentIndex(0)
        form.addRow("Reason *", self.reason)
        root.addLayout(form)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save adjustment")
        save.setDefault(True)
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    def _update_total(self) -> None:
        self.total_lbl.setText(f"= {self.qty.total_pieces()} pieces total")

    def _save(self) -> None:
        reason = self.reason.currentText().strip()
        if not reason:
            QMessageBox.warning(self, "Reason required",
                                "Please give a reason for the adjustment.")
            return
        ok, msg, _ = self.controller.adjust_stock(
            self.product_id, self.qty.total_pieces(), reason)
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not adjust stock", msg)
