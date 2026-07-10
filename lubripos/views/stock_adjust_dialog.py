"""Stock adjustment dialog: correct a product's on-hand quantity (stock-take).

This is a MANUAL override (not a purchase/sale), so it captures a reason and
writes a before/after entry to the audit log via the controller/service.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout,
)

from ..controllers.product_controller import ProductController

REASONS = ["Stock count correction", "Damaged", "Lost / theft",
           "Returned to supplier", "Expired", "Other"]


class StockAdjustDialog(QDialog):
    def __init__(self, controller: ProductController, product_id: int) -> None:
        super().__init__()
        self.controller = controller
        self.product_id = product_id
        self.product = controller.get(product_id)
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
        current = QLabel(str(self.product["stock_qty"]))
        form.addRow("Product", name)
        form.addRow("Current stock", current)

        self.new_qty = QSpinBox()
        self.new_qty.setRange(0, 100_000_000)
        self.new_qty.setValue(int(self.product["stock_qty"]))
        form.addRow("New counted qty *", self.new_qty)

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
        self.new_qty.setFocus()
        self.new_qty.selectAll()

    def _save(self) -> None:
        reason = self.reason.currentText().strip()
        if not reason:
            QMessageBox.warning(self, "Reason required",
                                "Please give a reason for the adjustment.")
            return
        ok, msg, _ = self.controller.adjust_stock(
            self.product_id, self.new_qty.value(), reason)
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not adjust stock", msg)
