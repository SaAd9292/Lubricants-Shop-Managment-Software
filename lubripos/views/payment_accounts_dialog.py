"""Manage payment accounts (admin) — named Bank / EasyPaisa / JazzCash.

Opened from Settings. Lets the admin add, edit, deactivate/activate and delete
the shop's mobile-wallet / bank accounts. Deactivated accounts stay out of the
POS dropdown but keep their history; deleting is safe (sales snapshot the name).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.payment_account_controller import PaymentAccountController
from ..services.payment_account_service import METHODS
from ..ui.widgets import DataTable

COLUMNS = ["Method", "Name", "Number", "Status"]


class _AccountForm(QDialog):
    """Add / edit a single account."""

    def __init__(self, parent=None, account: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit account" if account else "Add account")
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        self.method = QComboBox()
        self.method.addItems(list(METHODS))
        self.name = QLineEdit()
        self.number = QLineEdit()
        self.number.setPlaceholderText("Phone / account number (optional)")
        form.addRow("Method", self.method)
        form.addRow("Name *", self.name)
        form.addRow("Number", self.number)
        if account:
            self.method.setCurrentText(account.get("method", METHODS[0]))
            self.name.setText(account.get("name") or "")
            self.number.setText(account.get("account_no") or "")

        row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._ok)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        form.addRow(row)

    def _ok(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Required", "Account name is required.")
            return
        self.accept()

    def data(self) -> dict:
        return {"method": self.method.currentText(), "name": self.name.text().strip(),
                "account_no": self.number.text().strip()}


class PaymentAccountsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = PaymentAccountController(ctx)
        self.setWindowTitle("Payment Accounts")
        self.resize(560, 420)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        hint = QLabel("Bank, EasyPaisa and JazzCash accounts the shop receives "
                      "money into. The cashier picks one at checkout.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = "No accounts yet - click Add."
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._edit)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        row.addWidget(add)
        for label, slot in [("Edit", self._edit), ("Activate / Deactivate", self._toggle)]:
            b = QPushButton(label)
            b.setObjectName("Secondary")
            b.clicked.connect(slot)
            row.addWidget(b)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        row.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)

    # -- data ---------------------------------------------------------
    def _reload(self) -> None:
        rows = self.controller.list()
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            vals = [a["method"], a["name"], a.get("account_no") or "",
                    "Active" if a["is_active"] else "Inactive"]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.UserRole, a["id"])
                    item.setData(Qt.UserRole + 1, bool(a["is_active"]))
                if not a["is_active"]:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole), item.data(Qt.UserRole + 1)

    def _selected_account(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return {"id": self.table.item(row, 0).data(Qt.UserRole),
                "method": self.table.item(row, 0).text(),
                "name": self.table.item(row, 1).text(),
                "account_no": self.table.item(row, 2).text()}

    # -- actions ------------------------------------------------------
    def _add(self) -> None:
        dlg = _AccountForm(self)
        if dlg.exec():
            ok, msg, _ = self.controller.create(dlg.data())
            self._after(ok, msg)

    def _edit(self) -> None:
        acc = self._selected_account()
        if acc is None:
            QMessageBox.information(self, "Select an account", "Please select a row first.")
            return
        dlg = _AccountForm(self, account=acc)
        if dlg.exec():
            ok, msg, _ = self.controller.update(acc["id"], dlg.data())
            self._after(ok, msg)

    def _toggle(self) -> None:
        acc_id, active = self._selected()
        if acc_id is None:
            QMessageBox.information(self, "Select an account", "Please select a row first.")
            return
        ok, msg, _ = self.controller.set_active(acc_id, not active)
        self._after(ok, msg)

    def _delete(self) -> None:
        acc_id, _ = self._selected()
        if acc_id is None:
            QMessageBox.information(self, "Select an account", "Please select a row first.")
            return
        if QMessageBox.warning(
                self, "Delete account",
                "Delete this account? Past sales keep the account name, but it "
                "will be removed from the checkout list.\n\nTip: use "
                "Deactivate to just hide it.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.delete(acc_id)
        self._after(ok, msg)

    def _after(self, ok: bool, msg: str) -> None:
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)
