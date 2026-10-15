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

    def _open_payments(self) -> None:
        from .supplier_payments_dialog import SupplierPaymentsDialog
        SupplierPaymentsDialog(self.ctx, self).exec()

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
        payments_btn = QPushButton("Payment history")
        payments_btn.setObjectName("Secondary")
        payments_btn.setToolTip("List and print all payments made to suppliers")
        payments_btn.clicked.connect(self._open_payments)
        filters.addWidget(payments_btn)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("Secondary")
        refresh.clicked.connect(self._reload)
        filters.addWidget(refresh)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = "No supplier balances to show."
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        # rows carry a "Record payment" button; give them height so it isn't clipped
        self.table.verticalHeader().setDefaultSectionSize(44)
        # fixed-height rows: never let the last row stretch to fill empty space
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 172)
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
                btn.setFixedHeight(30)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _=False, sid=s["id"], nm=s["name"],
                                    bal=s["balance"]: self._record_payment(sid, nm, bal))
                # wrap with margins so the button sits INSIDE the cell (never
                # touching/overflowing the table's right edge)
                wrap = QWidget()
                wl = QHBoxLayout(wrap)
                wl.setContentsMargins(4, 3, 8, 3)
                wl.addWidget(btn)
                self.table.setCellWidget(r, 5, wrap)

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
        self.supplier_id = supplier_id
        # name for the title (all-time, no filter)
        try:
            name = controller.ledger(supplier_id)["supplier"]["name"]
        except Exception:
            name = ""
        self.setWindowTitle(f"Ledger — {name}")
        self.resize(720, 560)
        root = QVBoxLayout(self)

        # --- date filter bar ---
        bar = QHBoxLayout()
        self.all_cb = QCheckBox("All dates")
        self.all_cb.setChecked(True)
        self.all_cb.stateChanged.connect(self._on_toggle)
        bar.addWidget(self.all_cb)
        bar.addWidget(QLabel("From"))
        self.d_from = QDateEdit()
        self.d_from.setCalendarPopup(True)
        self.d_from.setDisplayFormat("dd MMM yyyy")
        self.d_from.setDate(QDate.currentDate().addMonths(-1))
        self.d_from.setEnabled(False)
        self.d_from.dateChanged.connect(lambda _=None: self._reload())
        bar.addWidget(self.d_from)
        bar.addWidget(QLabel("To"))
        self.d_to = QDateEdit()
        self.d_to.setCalendarPopup(True)
        self.d_to.setDisplayFormat("dd MMM yyyy")
        self.d_to.setDate(QDate.currentDate())
        self.d_to.setEnabled(False)
        self.d_to.dateChanged.connect(lambda _=None: self._reload())
        bar.addWidget(self.d_to)
        bar.addStretch(1)
        root.addLayout(bar)

        self.summary = QLabel("")
        self.summary.setObjectName("PageTitle")
        root.addWidget(self.summary)

        root.addWidget(QLabel("Purchases"))
        self.ptbl = DataTable(0, 5)
        self.ptbl.placeholder = "No purchases in this period."
        self.ptbl.setHorizontalHeaderLabels(
            ["Date", "Invoice", "Total", "Paid at purchase", "On credit"])
        self.ptbl.verticalHeader().setVisible(False)
        self.ptbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ptbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.ptbl, 1)

        root.addWidget(QLabel("Payments"))
        self.mtbl = DataTable(0, 4)
        self.mtbl.placeholder = "No payments in this period."
        self.mtbl.setHorizontalHeaderLabels(["Date", "Amount", "Method", "Notes"])
        self.mtbl.verticalHeader().setVisible(False)
        self.mtbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.mtbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        root.addWidget(self.mtbl, 1)

        self.rlbl = QLabel("Returns to supplier (debit notes)")
        root.addWidget(self.rlbl)
        self.rtbl = DataTable(0, 3)
        self.rtbl.placeholder = "No returns in this period."
        self.rtbl.setHorizontalHeaderLabels(["Date", "Amount", "Note"])
        self.rtbl.verticalHeader().setVisible(False)
        self.rtbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rtbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.rtbl, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addWidget(buttons)

        self._reload()

    def _on_toggle(self) -> None:
        on = not self.all_cb.isChecked()
        self.d_from.setEnabled(on)
        self.d_to.setEnabled(on)
        self._reload()

    def _reload(self) -> None:
        if self.all_cb.isChecked():
            df = dt = None
        else:
            df = self.d_from.date().toString("yyyy-MM-dd")
            dt = self.d_to.date().toString("yyyy-MM-dd")
        data = self.controller.ledger(self.supplier_id, date_from=df, date_to=dt)
        fmt = self.controller.fmt

        scope = "all time" if df is None else f"{df} → {dt}"
        summ = (f"Purchased: {fmt(data['purchased'])}    Paid: {fmt(data['paid'])}    ")
        if data.get("returned", 0):
            summ += f"Returned: {fmt(data['returned'])}    "
        summ += (f"({scope})      "
                 f"Current balance owed: {fmt(data['balance'])}")
        self.summary.setText(summ)

        purchases = data["purchases"]
        self.ptbl.setRowCount(len(purchases))
        for r, p in enumerate(purchases):
            self.ptbl.setItem(r, 0, QTableWidgetItem(p["date"]))
            self.ptbl.setItem(r, 1, QTableWidgetItem(p["invoice"]))
            self.ptbl.setItem(r, 2, _money_item(fmt(p["total"])))
            self.ptbl.setItem(r, 3, _money_item(fmt(p["paid_at"])))
            self.ptbl.setItem(r, 4, _money_item(fmt(p["credit"])))

        payments = data["payments"]
        self.mtbl.setRowCount(len(payments))
        for r, p in enumerate(payments):
            self.mtbl.setItem(r, 0, QTableWidgetItem(p["date"]))
            self.mtbl.setItem(r, 1, _money_item(fmt(p["amount"])))
            self.mtbl.setItem(r, 2, QTableWidgetItem(p["method"]))
            self.mtbl.setItem(r, 3, QTableWidgetItem(p["notes"]))

        returns = data.get("returns", [])
        self.rtbl.setRowCount(len(returns))
        for r, rr in enumerate(returns):
            self.rtbl.setItem(r, 0, QTableWidgetItem(rr["date"]))
            self.rtbl.setItem(r, 1, _money_item(fmt(rr["amount"])))
            self.rtbl.setItem(r, 2, QTableWidgetItem(rr.get("notes", "")))
