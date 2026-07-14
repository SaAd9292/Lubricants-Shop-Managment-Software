"""Supplier Payables page: how much the shop owes each supplier, with a
"Record payment" action and a per-supplier ledger (purchases + payments).

Reads are visible to anyone who can open the screen; recording a payment is
admin-only and enforced by the controller (the button is also hidden for
non-admins).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.session import current_session
from ..controllers.payable_controller import PayableController
from ..ui.widgets import DataTable

_METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]
# label, key, right-aligned?
COLUMNS = [("Supplier", "name", False), ("Phone", "phone", False),
           ("Purchased", "purchased", True), ("Paid", "paid", True),
           ("Balance owed", "balance", True), ("", None, False)]


def _money_item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class PayablesView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = PayableController(ctx)
        self._is_admin = bool(current_session.user and current_session.user.role == "admin")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Supplier Payables")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.total_lbl = QLabel("")
        self.total_lbl.setObjectName("PageTitle")
        header.addWidget(self.total_lbl)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search supplier…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_outstanding = QCheckBox("Only outstanding")
        self.f_outstanding.setChecked(True)
        self.f_outstanding.stateChanged.connect(self._reload)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_outstanding)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("Secondary")
        refresh.clicked.connect(self._reload)
        filters.addWidget(refresh)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = "No supplier balances to show."
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 140)
        self.table.doubleClicked.connect(lambda: self._open_ledger())
        root.addWidget(self.table, 1)

        hint = QLabel("Double-click a supplier to see its full ledger "
                      "(purchases and payments).")
        hint.setObjectName("Muted")
        root.addWidget(hint)

    # -- data ---------------------------------------------------------
    def _reload(self) -> None:
        res = self.controller.list(
            search=self.search.text(),
            only_outstanding=self.f_outstanding.isChecked())
        self._populate(res["rows"])
        self.total_lbl.setText(f"Total owed:  {self.controller.fmt(res['total_balance'])}")

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            name = QTableWidgetItem(s["name"])
            name.setData(Qt.UserRole, s["id"])
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(s.get("phone") or ""))
            self.table.setItem(r, 2, _money_item(self.controller.fmt(s["purchased"])))
            self.table.setItem(r, 3, _money_item(self.controller.fmt(s["paid"])))
            self.table.setItem(r, 4, _money_item(self.controller.fmt(s["balance"])))
            if self._is_admin:
                btn = QPushButton("Record payment")
                btn.setObjectName("Success")
                btn.clicked.connect(lambda _=False, sid=s["id"], nm=s["name"],
                                    bal=s["balance"]: self._record_payment(sid, nm, bal))
                self.table.setCellWidget(r, 5, btn)

    def _selected(self) -> tuple[int, str] | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return (it.data(Qt.UserRole), it.text()) if it else None

    # -- actions ------------------------------------------------------
    def _record_payment(self, supplier_id: int, name: str, balance: int) -> None:
        _, mu = self.controller.currency()
        dlg = RecordPaymentDialog(self, name, balance / mu)
        if dlg.exec() != QDialog.Accepted:
            return
        data = dlg.values()
        ok, msg, _ = self.controller.record_payment(
            supplier_id, data["amount"], method=data["method"],
            notes=data["notes"], payment_date=data["date"])
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Payment failed", msg)

    def _open_ledger(self) -> None:
        sel = self._selected()
        if not sel:
            return
        LedgerDialog(self, self.controller, sel[0]).exec()


class RecordPaymentDialog(QDialog):
    def __init__(self, parent, supplier_name: str, balance_dec: float) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Record payment — {supplier_name}")
        self.setMinimumWidth(360)
        form = QFormLayout(self)

        self.amount = QDoubleSpinBox()
        self.amount.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.amount.setDecimals(2)
        self.amount.setMaximum(1_000_000_000)
        self.amount.setValue(max(0.0, round(balance_dec, 2)))
        form.addRow("Amount", self.amount)

        self.method = QComboBox()
        self.method.addItems(_METHODS)
        form.addRow("Method", self.method)

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(QDate.currentDate())
        form.addRow("Date", self.date)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional note (cheque no, reference…)")
        form.addRow("Notes", self.notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save = buttons.button(QDialogButtonBox.Save)
        save.setText("Record payment")
        save.setObjectName("Success")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        if self.amount.value() <= 0:
            QMessageBox.information(self, "Amount required",
                                    "Enter a payment amount greater than zero.")
            return
        self.accept()

    def values(self) -> dict:
        return {"amount": self.amount.value(),
                "method": self.method.currentText(),
                "date": self.date.date().toString("yyyy-MM-dd"),
                "notes": self.notes.text().strip()}


class LedgerDialog(QDialog):
    def __init__(self, parent, controller: PayableController, supplier_id: int) -> None:
        super().__init__(parent)
        self.controller = controller
        data = controller.ledger(supplier_id)
        sup = data["supplier"]
        self.setWindowTitle(f"Ledger — {sup['name']}")
        self.resize(680, 520)
        root = QVBoxLayout(self)

        summary = QLabel(
            f"Purchased: {controller.fmt(data['purchased'])}    "
            f"Paid: {controller.fmt(data['paid'])}    "
            f"Balance owed: {controller.fmt(data['balance'])}")
        summary.setObjectName("PageTitle")
        root.addWidget(summary)

        root.addWidget(QLabel("Purchases"))
        pcols = ["Date", "Invoice", "Total", "Paid at purchase", "On credit"]
        ptbl = DataTable(0, len(pcols))
        ptbl.placeholder = "No purchases from this supplier."
        ptbl.setHorizontalHeaderLabels(pcols)
        ptbl.verticalHeader().setVisible(False)
        ptbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ptbl.setRowCount(len(data["purchases"]))
        for r, p in enumerate(data["purchases"]):
            ptbl.setItem(r, 0, QTableWidgetItem(p["date"]))
            ptbl.setItem(r, 1, QTableWidgetItem(p["invoice"]))
            ptbl.setItem(r, 2, _money_item(controller.fmt(p["total"])))
            ptbl.setItem(r, 3, _money_item(controller.fmt(p["paid_at"])))
            ptbl.setItem(r, 4, _money_item(controller.fmt(p["credit"])))
        ptbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(ptbl, 1)

        root.addWidget(QLabel("Payments"))
        mcols = ["Date", "Amount", "Method", "Notes"]
        mtbl = DataTable(0, len(mcols))
        mtbl.placeholder = "No payments recorded yet."
        mtbl.setHorizontalHeaderLabels(mcols)
        mtbl.verticalHeader().setVisible(False)
        mtbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        mtbl.setRowCount(len(data["payments"]))
        for r, p in enumerate(data["payments"]):
            mtbl.setItem(r, 0, QTableWidgetItem(p["date"]))
            mtbl.setItem(r, 1, _money_item(controller.fmt(p["amount"])))
            mtbl.setItem(r, 2, QTableWidgetItem(p["method"]))
            mtbl.setItem(r, 3, QTableWidgetItem(p["notes"]))
        mtbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        root.addWidget(mtbl, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addWidget(buttons)
