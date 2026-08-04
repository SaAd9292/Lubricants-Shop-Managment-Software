"""Customers page: directory of customers with per-customer purchase history
("which oil did they buy last time?"). Searchable, sortable, paginated.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.customer_controller import CustomerController
from ..controllers.payment_account_controller import PaymentAccountController
from ..ui.widgets import DataTable, FlowLayout

PAGE_SIZE = 25
# label, sort key, right-aligned?
COLUMNS = [("Name", "name", False), ("Phone", None, False),
           ("Sales", "sales_count", True), ("Last purchase", "last_purchase", False),
           ("Total spent", "total_spent", True),
           ("Balance owed", "balance_owed", True)]


def _money_item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class CustomersView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = CustomerController(ctx)
        self._page = 0
        self._total = 0
        self._sort_by = "name"
        self._sort_dir = "asc"
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
        title = QLabel("Customers")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add Customer")
        add_btn.clicked.connect(self._add)
        header.addWidget(add_btn)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or phone…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_inactive = QCheckBox("Show inactive")
        self.f_inactive.stateChanged.connect(self._reset_and_reload)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_inactive)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = ("No customers yet. They're added automatically "
                                  "when you attach one to a sale, or click "
                                  '"+ Add Customer".')
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._on_sort)
        self.table.doubleClicked.connect(lambda: self._open_history())
        root.addWidget(self.table, 1)

        hint = QLabel("Double-click a customer to see their purchase history.")
        hint.setObjectName("Muted")
        root.addWidget(hint)

        footer = QHBoxLayout()
        hist_btn = QPushButton("View history")
        hist_btn.setObjectName("Secondary")
        hist_btn.clicked.connect(self._open_history)
        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("Secondary")
        edit_btn.clicked.connect(self._edit_selected)
        self.del_btn = QPushButton("Remove")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.clicked.connect(self._delete_selected)
        debt_btn = QPushButton("Debts / payments")
        debt_btn.setObjectName("Secondary")
        debt_btn.clicked.connect(self._open_ledger)
        footer.addWidget(hist_btn)
        footer.addWidget(debt_btn)
        footer.addWidget(edit_btn)
        footer.addWidget(self.del_btn)
        footer.addStretch(1)
        self.prev_btn = QPushButton("‹ Prev")
        self.prev_btn.setObjectName("Secondary")
        self.prev_btn.clicked.connect(self._prev)
        self.page_label = QLabel("")
        self.page_label.setObjectName("Muted")
        self.next_btn = QPushButton("Next ›")
        self.next_btn.setObjectName("Secondary")
        self.next_btn.clicked.connect(self._next)
        footer.addWidget(self.prev_btn)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)

    # -- data ---------------------------------------------------------
    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        res = self.controller.list(
            search=self.search.text(), only_active=not self.f_inactive.isChecked(),
            sort_by=self._sort_by, sort_dir=self._sort_dir,
            limit=PAGE_SIZE, offset=self._page * PAGE_SIZE)
        self._total = res["total"]
        self._populate(res["rows"])
        self._update_pagination()

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            name = QTableWidgetItem(c["name"] + ("" if c["is_active"] else "  (inactive)"))
            name.setData(Qt.UserRole, c["id"])
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(c.get("phone") or ""))
            n = _money_item(str(c.get("sales_count", 0)))
            self.table.setItem(r, 2, n)
            last = (c.get("last_purchase") or "")[:16]
            self.table.setItem(r, 3, QTableWidgetItem(last or "—"))
            self.table.setItem(r, 4, _money_item(self.controller.fmt(c.get("total_spent", 0))))
            bal = int(c.get("balance_owed", 0) or 0)
            bcell = _money_item(self.controller.fmt(bal) if bal else "—")
            if bal > 0:
                bcell.setForeground(QColor("#dc2626"))   # owes money -> red
            self.table.setItem(r, 5, bcell)

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} customers)")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page + 1 < pages)

    def _prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._reload()

    def _next(self) -> None:
        if (self._page + 1) * PAGE_SIZE < self._total:
            self._page += 1
            self._reload()

    def _on_sort(self, col: int) -> None:
        key = COLUMNS[col][1]
        if not key:
            return
        if self._sort_by == key:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_by, self._sort_dir = key, "asc"
        self._page = 0
        self._reload()

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    # -- actions ------------------------------------------------------
    def _add(self) -> None:
        if CustomerEditDialog(self.controller).exec():
            self._reset_and_reload()

    def _edit_selected(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Select a customer", "Please select a row first.")
            return
        if CustomerEditDialog(self.controller, customer_id=cid).exec():
            self._reload()

    def _open_history(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Select a customer", "Please select a row first.")
            return
        CustomerHistoryDialog(self, self.controller, cid).exec()

    def _open_ledger(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "No selection", "Select a customer first.")
            return
        CustomerLedgerDialog(self, self.controller, cid).exec()
        self._reload()   # balance may have changed

    def _delete_selected(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Select a customer", "Please select a row first.")
            return
        if self.f_inactive.isChecked():
            ok, msg, _ = self.controller.reactivate(cid)
        else:
            if QMessageBox.question(self, "Remove customer",
                                    "Remove this customer? Their past sales are kept."
                                    ) != QMessageBox.Yes:
                return
            ok, msg, _ = self.controller.remove(cid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)


class CustomerEditDialog(QDialog):
    def __init__(self, controller: CustomerController, customer_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.customer_id = customer_id
        self.setWindowTitle("Edit Customer" if customer_id else "Add Customer")
        self.setMinimumWidth(340)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.notes = QLineEdit()
        # opening balance: money the customer already owed on paper before going
        # digital. Adds straight into their "balance owed".
        self.opening = QDoubleSpinBox()
        self.opening.setMaximum(99_999_999)
        self.opening.setDecimals(2)
        self.opening.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.opening.setToolTip("Money this customer already owed from your paper "
                                "records. Leave 0 for a brand-new customer.")
        form.addRow("Name", self.name)
        form.addRow("Phone", self.phone)
        form.addRow("Opening balance owed", self.opening)
        form.addRow("Notes", self.notes)
        _, self._mu = controller.currency()
        if customer_id is not None:
            c = controller.get(customer_id)
            self.name.setText(c.get("name") or "")
            self.phone.setText(c.get("phone") or "")
            self.notes.setText(c.get("notes") or "")
            self.opening.setValue((c.get("opening_debt_minor") or 0) / self._mu)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setObjectName("Success")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _save(self) -> None:
        form = {"name": self.name.text().strip(), "phone": self.phone.text().strip(),
                "notes": self.notes.text().strip(),
                "opening_debt": self.opening.value()}
        if not form["name"]:
            QMessageBox.information(self, "Name required", "Enter a customer name.")
            return
        ok, msg, _ = self.controller.save(form, self.customer_id)
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)


class CustomerHistoryDialog(QDialog):
    def __init__(self, parent, controller: CustomerController, customer_id: int) -> None:
        super().__init__(parent)
        self.controller = controller
        data = controller.history(customer_id)
        cust = data["customer"]
        self.setWindowTitle(f"History — {cust['name']}")
        self.resize(700, 540)
        root = QVBoxLayout(self)

        head = QLabel(f"{cust['name']}"
                      + (f"   ·   {cust['phone']}" if cust.get("phone") else "")
                      + f"      Visits: {data['visits']}      "
                      f"Total spent: {controller.fmt(data['total_spent'])}")
        head.setObjectName("PageTitle")
        root.addWidget(head)

        root.addWidget(QLabel("Products bought"))
        pcols = ["Product", "Total qty", "Visits", "Last price", "Last bought"]
        ptbl = DataTable(0, len(pcols))
        ptbl.placeholder = "No purchases on record."
        ptbl.setHorizontalHeaderLabels(pcols)
        ptbl.verticalHeader().setVisible(False)
        ptbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ptbl.setRowCount(len(data["products"]))
        for r, p in enumerate(data["products"]):
            ptbl.setItem(r, 0, QTableWidgetItem(p["product"]))
            ptbl.setItem(r, 1, _money_item(str(p["qty"])))
            ptbl.setItem(r, 2, _money_item(str(p["visits"])))
            ptbl.setItem(r, 3, _money_item(controller.fmt(p["last_price"] or 0)))
            ptbl.setItem(r, 4, QTableWidgetItem((p["last_date"] or "")[:16]))
        ptbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        root.addWidget(ptbl, 1)

        root.addWidget(QLabel("Sales"))
        scols = ["Invoice", "Date", "Items", "Total"]
        stbl = DataTable(0, len(scols))
        stbl.placeholder = "No sales on record."
        stbl.setHorizontalHeaderLabels(scols)
        stbl.verticalHeader().setVisible(False)
        stbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        stbl.setRowCount(len(data["sales"]))
        for r, sr in enumerate(data["sales"]):
            stbl.setItem(r, 0, QTableWidgetItem(sr["invoice"]))
            stbl.setItem(r, 1, QTableWidgetItem(sr["date"]))
            stbl.setItem(r, 2, _money_item(str(sr["items"])))
            stbl.setItem(r, 3, _money_item(controller.fmt(sr["total"])))
        stbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(stbl, 1)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addWidget(box)


class CustomerLedgerDialog(QDialog):
    """Shows one customer's credit (udhaar) ledger — every unpaid 'Debt' sale
    and every repayment — with the current balance owed, plus a small form to
    record a new repayment against the tab."""

    _METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]

    def __init__(self, parent, controller: CustomerController, customer_id: int) -> None:
        super().__init__(parent)
        self.controller = controller
        self.pay_ctl = PaymentAccountController(controller.ctx)
        self.customer_id = customer_id
        self.setWindowTitle("Debts / payments")
        self.resize(680, 560)
        self._build()
        self._refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setObjectName("PageTitle")
        root.addWidget(self.head)
        self.balance_lbl = QLabel("")
        self.balance_lbl.setStyleSheet("font-size:16px; font-weight:700;")
        root.addWidget(self.balance_lbl)

        root.addWidget(QLabel("Ledger (charges on credit, and repayments)"))
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Date", "Type", "Detail", "Amount"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.tbl, 1)

        # -- record a repayment (laid out like the Sale screen's Payment panel) --
        pay_title = QLabel("Record payment")
        pay_title.setStyleSheet("font-size:14px; font-weight:700; margin-top:6px;")
        root.addWidget(pay_title)

        # payment method as selectable chips, exactly like the POS
        self._method_group = QButtonGroup(self)
        self._method_group.setExclusive(True)
        chips = FlowLayout(spacing=6)
        for m in self._METHODS:
            chip = QPushButton(m)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setMinimumWidth(chip.sizeHint().width())
            if m == "Cash":
                chip.setChecked(True)
            self._method_group.addButton(chip)
            chips.addWidget(chip)
        root.addLayout(chips)
        self._method_group.buttonClicked.connect(lambda _b: self._reload_pay_accounts())

        form = QFormLayout()
        self.account = QComboBox()
        self.amount = QDoubleSpinBox()
        self.amount.setMaximum(99_999_999)
        self.amount.setDecimals(2)
        self.amount.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.pay_notes = QLineEdit()
        self.pay_notes.setPlaceholderText("Optional note")
        self._acct_label = QLabel("Account:")
        form.addRow(self._acct_label, self.account)
        form.addRow("Amount paid:", self.amount)
        form.addRow("Note:", self.pay_notes)
        root.addLayout(form)
        self._reload_pay_accounts()

        bar = QHBoxLayout()
        bar.addStretch(1)
        pay_btn = QPushButton("Record payment")
        pay_btn.setObjectName("Success")
        pay_btn.clicked.connect(self._record)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("Secondary")
        close_btn.clicked.connect(self.accept)
        bar.addWidget(pay_btn)
        bar.addWidget(close_btn)
        root.addLayout(bar)

    def _selected_method(self) -> str:
        btn = self._method_group.checkedButton()
        return btn.text() if btn else "Cash"

    def _reload_pay_accounts(self) -> None:
        """Bank / EasyPaisa / JazzCash need a specific account (like the POS);
        Cash has none. Each item carries (account_id, account_name)."""
        m = self._selected_method()
        self.account.clear()
        if m == "Cash":
            # cash needs no account — hide the whole row so it's not asked for
            self._acct_label.setVisible(False)
            self.account.setVisible(False)
            self.account.addItem("", (None, None))
            return
        self._acct_label.setVisible(True)
        self.account.setVisible(True)
        accts = self.pay_ctl.list(method=m, active_only=True)
        if not accts:
            self.account.addItem("(no accounts — add in Settings)", (None, None))
            self.account.setEnabled(False)
            return
        self.account.setEnabled(True)
        for a in accts:
            label = a["name"] + (f" — {a['account_no']}" if a.get("account_no") else "")
            self.account.addItem(label, (a["id"], a["name"]))

    def _refresh(self) -> None:
        data = self.controller.ledger(self.customer_id)
        cust = data["customer"]
        fmt = self.controller.fmt
        self.head.setText(cust["name"]
                          + (f"   ·   {cust['phone']}" if cust.get("phone") else ""))
        bal = data["balance"]
        self.balance_lbl.setText("Balance owed:  " + (fmt(bal) if bal else fmt(0)))
        self.balance_lbl.setStyleSheet(
            "font-size:16px; font-weight:700; color:%s;"
            % ("#dc2626" if bal > 0 else "#16a34a"))

        # merge charges (+) and payments (-) into one date-ordered view
        entries = []
        for c in data["charges"]:
            entries.append((c["date"], "Purchase (credit)",
                            f"Invoice {c['ref']}", c["amount"], "#dc2626"))
        for p in data["payments"]:
            detail = p.get("method") or ""
            if p.get("notes"):
                detail = (detail + " — " + p["notes"]).strip(" —")
            entries.append((p["date"], "Payment", detail or "Repayment",
                            -p["amount"], "#16a34a"))
        entries.sort(key=lambda e: e[0])
        self.tbl.setRowCount(len(entries))
        for r, (dt, typ, detail, amt, color) in enumerate(entries):
            self.tbl.setItem(r, 0, QTableWidgetItem(dt))
            self.tbl.setItem(r, 1, QTableWidgetItem(typ))
            self.tbl.setItem(r, 2, QTableWidgetItem(detail))
            it = _money_item(("-" if amt < 0 else "") + fmt(abs(amt)))
            it.setForeground(QColor(color))
            self.tbl.setItem(r, 3, it)

    def _record(self) -> None:
        amt = self.amount.value()
        if amt <= 0:
            QMessageBox.information(self, "Enter amount",
                                    "Enter a payment amount greater than zero.")
            return
        method = self._selected_method()
        acct_id, acct_name = self.account.currentData() or (None, None)
        if method != "Cash" and acct_id is None:
            QMessageBox.information(
                self, "Choose an account",
                f"Select which {method} account received the money "
                "(or add one in Settings → Payment Accounts).")
            return
        ok, msg, pay_id = self.controller.record_payment(
            self.customer_id, amt, method=method, account_id=acct_id,
            account_name=acct_name, notes=self.pay_notes.text())
        if not ok:
            QMessageBox.warning(self, "Could not record payment", msg)
            return
        self.amount.setValue(0)
        self.pay_notes.clear()
        self._refresh()
        # give the customer a printable receipt
        rok, rmsg, path = self.controller.payment_receipt(pay_id)
        if rok:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(
                self, "Payment saved",
                "Payment recorded, but the receipt could not be created:\n" + rmsg)
