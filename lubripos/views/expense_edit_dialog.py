"""Add / Edit expense dialog."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..controllers.expense_controller import ExpenseController


class ExpenseEditDialog(QDialog):
    def __init__(self, controller: ExpenseController, expense_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.expense_id = expense_id
        self._minor_units = controller.currency()[1]
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self.setWindowTitle("Edit Expense" if expense_id else "Add Expense")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load_categories()
        if expense_id:
            self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(QDate.currentDate())

        self.category = QComboBox()
        cat_row = QWidget()
        cl = QHBoxLayout(cat_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.category, 1)
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(36)
        add_btn.setObjectName("Secondary")
        add_btn.clicked.connect(self._add_category)
        cl.addWidget(add_btn)

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000_000)
        self.amount.setDecimals(self._decimals)
        self.amount.setGroupSeparatorShown(True)

        self.description = QLineEdit()

        form.addRow("Date", self.date)
        form.addRow("Category *", cat_row)
        form.addRow("Amount *", self.amount)
        form.addRow("Description", self.description)
        root.addLayout(form)

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

    def _load_categories(self) -> None:
        self.category.clear()
        for c in self.controller.categories():
            self.category.addItem(c["name"], c["name"])

    def _add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "Add category", "Category name:")
        if ok and name.strip():
            success, msg, _ = self.controller.add_category(name.strip())
            if success:
                self._load_categories()
                self.category.setCurrentText(name.strip())
            else:
                QMessageBox.warning(self, "Error", msg)

    def _load(self) -> None:
        e = self.controller.get(self.expense_id)
        d = (e.get("expense_date") or "")[:10]
        try:
            self.date.setDate(QDate.fromString(d, "yyyy-MM-dd"))
        except Exception:
            pass
        idx = self.category.findData(e.get("category"))
        if idx < 0:
            self.category.addItem(e.get("category"), e.get("category"))
            idx = self.category.findData(e.get("category"))
        self.category.setCurrentIndex(max(0, idx))
        self.amount.setValue(float(Decimal(e["amount_minor"]) / self._minor_units))
        self.description.setText(e.get("description") or "")

    def _save(self) -> None:
        if not self.category.currentText().strip():
            QMessageBox.warning(self, "Required", "Please choose a category.")
            return
        if self.amount.value() <= 0:
            QMessageBox.warning(self, "Required", "Amount must be greater than zero.")
            return
        form: dict[str, Any] = {
            "expense_date": self.date.date().toString("yyyy-MM-dd") + " 00:00:00",
            "category": self.category.currentText().strip(),
            "amount": self.amount.value(),
            "description": self.description.text().strip(),
        }
        ok, msg, _ = self.controller.save(form, self.expense_id)
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)
