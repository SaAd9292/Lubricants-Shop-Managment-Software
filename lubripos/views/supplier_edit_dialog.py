"""Add / Edit supplier dialog (fast-entry: auto-focus, Enter saves, add-another)."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from ..controllers.supplier_controller import SupplierController


class SupplierEditDialog(QDialog):
    def __init__(self, controller: SupplierController, supplier_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.supplier_id = supplier_id
        self._saved_any = False
        self.setWindowTitle("Edit Supplier" if supplier_id else "Add Supplier")
        self.setMinimumWidth(420)
        self._build_ui()
        if supplier_id:
            self._load()
        self.name.setFocus()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.address = QPlainTextEdit()
        self.address.setFixedHeight(60)
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(60)
        form.addRow("Name *", self.name)
        form.addRow("Phone", self.phone)
        form.addRow("Address", self.address)
        form.addRow("Notes", self.notes)
        root.addLayout(form)

        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self._close)
        actions.addWidget(cancel)
        actions.addStretch(1)
        if self.supplier_id is None:
            add_more = QPushButton("Save && add another")
            add_more.setObjectName("Secondary")
            add_more.clicked.connect(lambda: self._save(add_another=True))
            actions.addWidget(add_more)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(lambda: self._save())
        actions.addWidget(save)
        root.addLayout(actions)

    def _load(self) -> None:
        s = self.controller.get(self.supplier_id)
        self.name.setText(s["name"])
        self.phone.setText(s.get("phone") or "")
        self.address.setPlainText(s.get("address") or "")
        self.notes.setPlainText(s.get("notes") or "")

    def _save(self, add_another: bool = False) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Required", "Supplier name is required.")
            return
        form: dict[str, Any] = {
            "name": self.name.text().strip(),
            "phone": self.phone.text().strip(),
            "address": self.address.toPlainText().strip(),
            "notes": self.notes.toPlainText().strip(),
        }
        ok, msg, _ = self.controller.save(form, self.supplier_id)
        if not ok:
            QMessageBox.warning(self, "Could not save", msg)
            return
        if add_another:
            self._saved_any = True
            self.name.clear()
            self.phone.clear()
            self.address.clear()
            self.notes.clear()
            self.name.setFocus()
        else:
            self.accept()

    def _close(self) -> None:
        self.accept() if self._saved_any else self.reject()
