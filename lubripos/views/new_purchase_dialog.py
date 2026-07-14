"""New Purchase dialog: pick a supplier, add product lines, save.

Saving records the purchase and increases each product's stock atomically
(handled in PurchaseService within a single transaction).
"""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..controllers.purchase_controller import PurchaseController
from ..core import money
from .product_picker_dialog import ProductPickerDialog


class NewPurchaseDialog(QDialog):
    def __init__(self, controller: PurchaseController) -> None:
        super().__init__()
        self.controller = controller
        self._symbol, self._minor_units = controller.currency()
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self._updating = False
        self.setWindowTitle("New Purchase")
        self.setMinimumSize(680, 540)
        self._build_ui()

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(12)

        title = QLabel("New Purchase")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        # header form
        form = QFormLayout()
        self.supplier = QComboBox()
        self.supplier.addItem("— Select supplier —", None)
        for s in self.controller.active_suppliers():
            self.supplier.addItem(s["name"], s["id"])
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(QDate.currentDate())
        self.invoice_no = QLineEdit()
        self.invoice_no.setPlaceholderText("Supplier's invoice/bill no (optional)")
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Notes (optional)")
        form.addRow("Supplier", self.supplier)
        form.addRow("Date", self.date)
        form.addRow("Supplier invoice #", self.invoice_no)
        form.addRow("Notes", self.notes)
        root.addLayout(form)

        # line items table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Qty", f"Unit cost ({self._symbol})", "Line total"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        line_actions = QHBoxLayout()
        add_line = QPushButton("+ Add product")
        add_line.clicked.connect(self._add_product)
        remove_line = QPushButton("Remove line")
        remove_line.setObjectName("Secondary")
        remove_line.clicked.connect(self._remove_line)
        line_actions.addWidget(add_line)
        line_actions.addWidget(remove_line)
        line_actions.addStretch(1)
        self.total_label = QLabel(self._fmt_total(0))
        self.total_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        line_actions.addWidget(self.total_label)
        root.addLayout(line_actions)

        # dialog actions
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save purchase")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    # -- line management ----------------------------------------------
    def _add_product(self) -> None:
        picker = ProductPickerDialog(self.controller.search_products, self.controller.fmt)
        if not picker.exec() or not picker.selected:
            return
        p = picker.selected
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(p["name"])
        name_item.setData(Qt.UserRole, p["id"])
        self.table.setItem(row, 0, name_item)

        qty = QSpinBox()
        qty.setRange(1, 1_000_000)
        qty.setValue(1)
        qty.valueChanged.connect(self._recompute)
        self.table.setCellWidget(row, 1, qty)

        cost = QDoubleSpinBox()
        cost.setRange(0, 1_000_000_000)
        cost.setButtonSymbols(QAbstractSpinBox.NoButtons)
        cost.setDecimals(self._decimals)
        cost.setGroupSeparatorShown(True)
        cost.setValue(float(p["purchase_price_minor"]) / self._minor_units)
        cost.valueChanged.connect(self._recompute)
        self.table.setCellWidget(row, 2, cost)

        total_item = QTableWidgetItem("")
        total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 3, total_item)

        self._recompute()

    def _remove_line(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._recompute()

    def _recompute(self) -> None:
        if self._updating:
            return
        grand = 0
        for row in range(self.table.rowCount()):
            qty_w = self.table.cellWidget(row, 1)
            cost_w = self.table.cellWidget(row, 2)
            if qty_w is None or cost_w is None:
                continue
            qty = qty_w.value()
            unit_minor = money.to_minor(cost_w.value(), self._minor_units)
            line_minor = qty * unit_minor
            grand += line_minor
            self.table.item(row, 3).setText(
                money.format_money(line_minor, self._symbol, self._minor_units)
            )
        self.total_label.setText(self._fmt_total(grand))

    def _fmt_total(self, minor: int) -> str:
        return "Total:  " + money.format_money(minor, self._symbol, self._minor_units)

    # -- save ---------------------------------------------------------
    def _save(self) -> None:
        if self.supplier.currentData() is None:
            QMessageBox.warning(self, "Supplier required", "Please select a supplier.")
            return
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "No items", "Add at least one product line.")
            return

        lines = []
        for row in range(self.table.rowCount()):
            lines.append({
                "product_id": self.table.item(row, 0).data(Qt.UserRole),
                "qty": self.table.cellWidget(row, 1).value(),
                "unit_cost": self.table.cellWidget(row, 2).value(),
            })

        ok, msg, _ = self.controller.create(
            supplier_id=self.supplier.currentData(),
            lines=lines,
            purchase_date=self.date.date().toString("yyyy-MM-dd") + " 00:00:00",
            supplier_invoice_no=self.invoice_no.text().strip() or None,
            notes=self.notes.text().strip() or None,
        )
        if ok:
            QMessageBox.information(self, "Saved", "Purchase recorded and stock updated.")
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)
