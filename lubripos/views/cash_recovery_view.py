"""Cash Recovery — record money recovered against a customer's outstanding
credit (udhaar) balance.

A deliberately simple, dialog-style page: find the customer, see what they owe,
enter the amount recovered and how it came in (Cash / Bank / EasyPaisa /
JazzCash), and record it. A printable receipt is produced for the customer.

This is the same underlying action as the old in-Customers repayment form
(CustomerController.record_payment -> customer_payments), now a first-class
sidebar screen. Cash-method recoveries flow into the running Cash-in-Hand and
the Day-Close report automatically.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QStringListModel, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QCompleter, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.customer_controller import CustomerController
from ..controllers.payment_account_controller import PaymentAccountController
from ..core.session import current_session
from ..ui.toast import show_toast
from ..ui.widgets import FlowLayout

_METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]


class CashRecoveryView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = CustomerController(ctx)
        self.pay_ctl = PaymentAccountController(ctx)
        self._index: dict[str, dict] = {}     # name.lower -> customer row
        self._customer: dict | None = None
        self._build_ui()
        self._refresh_customers()

    # -- ui -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)

        title = QLabel("Cash Recovery")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        # centre a dialog-style card
        center = QHBoxLayout()
        center.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(540)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(12)

        sub = QLabel("Record money recovered against a customer's outstanding "
                     "balance (udhaar).")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        cl.addWidget(sub)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        # customer type-ahead
        self.cust = QLineEdit()
        self.cust.setPlaceholderText("Type the customer's name…")
        self._suggest = QCompleter(self)
        self._suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._suggest.setFilterMode(Qt.MatchContains)
        self._suggest.setCompletionMode(QCompleter.PopupCompletion)
        self._suggest.setMaxVisibleItems(10)
        self.cust.setCompleter(self._suggest)
        self._suggest.activated[str].connect(self._on_pick)
        self.cust.editingFinished.connect(self._sync_customer)
        form.addRow("Customer", self.cust)
        cl.addLayout(form)

        # balance owed (updates when a customer is chosen)
        self.balance_lbl = QLabel("Select a customer to see their balance.")
        self.balance_lbl.setStyleSheet("font-size:15px; font-weight:700;")
        cl.addWidget(self.balance_lbl)

        # payment method chips (like the POS)
        chips = FlowLayout(spacing=6)
        self._method_group = QButtonGroup(self)
        self._method_group.setExclusive(True)
        for m in _METHODS:
            chip = QPushButton(m)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            if m == "Cash":
                chip.setChecked(True)
            self._method_group.addButton(chip)
            chips.addWidget(chip)
        self._method_group.buttonClicked.connect(lambda _b: self._reload_accounts())
        cl.addLayout(chips)

        form2 = QFormLayout()
        form2.setHorizontalSpacing(14)
        form2.setVerticalSpacing(10)
        self._acct_label = QLabel("Account")
        self.account = QComboBox()
        form2.addRow(self._acct_label, self.account)

        sym, _ = self.controller.currency()
        self.amount = QDoubleSpinBox()
        self.amount.setMaximum(99_999_999)
        self.amount.setDecimals(2)
        self.amount.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.amount.setPrefix(f"{sym} ")
        form2.addRow("Amount recovered", self.amount)

        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional note")
        form2.addRow("Note", self.note)
        cl.addLayout(form2)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.record_btn = QPushButton("Record recovery")
        self.record_btn.setObjectName("Success")
        self.record_btn.setMinimumHeight(38)
        self.record_btn.clicked.connect(self._record)
        bar.addWidget(self.record_btn)
        cl.addLayout(bar)

        center.addWidget(card)
        center.addStretch(1)
        root.addLayout(center)
        root.addStretch(1)

        self._reload_accounts()

    # -- nav hook -----------------------------------------------------
    def _reload(self) -> None:
        """Refresh the customer list + the selected customer's balance whenever
        the screen is shown (a new debt sale may have changed it)."""
        self._refresh_customers()
        self._sync_customer()

    # -- customers ----------------------------------------------------
    def _refresh_customers(self) -> None:
        try:
            rows = self.controller.list(search="", limit=100000)["rows"]
        except Exception:
            rows = []
        self._index = {}
        names: list[str] = []
        for c in rows:
            key = (c.get("name") or "").lower()
            if key and key not in self._index:
                self._index[key] = c
                names.append(c["name"])
        self._suggest.setModel(QStringListModel(names, self._suggest))

    def _on_pick(self, text: str) -> None:
        self._sync_customer(text)

    def _sync_customer(self, text: str | None = None) -> None:
        name = (text if text is not None else self.cust.text()).strip().lower()
        c = self._index.get(name)
        self._customer = c
        if not c:
            self.balance_lbl.setText("Select a customer to see their balance.")
            self.balance_lbl.setStyleSheet("font-size:15px; font-weight:700;")
            return
        # pull the freshest balance (the index snapshot can be stale)
        try:
            bal = self.controller.balance_owed(c["id"])
        except Exception:
            bal = int(c.get("balance_owed") or 0)
        c["balance_owed"] = bal
        fmt = self.controller.fmt
        if bal > 0:
            self.balance_lbl.setText(f"Balance owed:  {fmt(bal)}")
            color = "#dc2626"
        elif bal < 0:
            self.balance_lbl.setText(f"In credit (advance):  {fmt(-bal)}")
            color = "#16a34a"
        else:
            self.balance_lbl.setText("Balance owed:  " + fmt(0))
            color = "#16a34a"
        self.balance_lbl.setStyleSheet(
            f"font-size:15px; font-weight:700; color:{color};")

    # -- payment accounts --------------------------------------------
    def _selected_method(self) -> str:
        btn = self._method_group.checkedButton()
        return btn.text() if btn else "Cash"

    def _reload_accounts(self) -> None:
        m = self._selected_method()
        self.account.clear()
        if m == "Cash":
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

    # -- record -------------------------------------------------------
    def _record(self) -> None:
        if not current_session.can("customers"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the Customers privilege.")
            return
        if not self._customer:
            QMessageBox.information(self, "Pick a customer",
                                    "Choose a customer from the list first.")
            self.cust.setFocus()
            return
        amt = self.amount.value()
        if amt <= 0:
            QMessageBox.information(self, "Enter amount",
                                    "Enter an amount greater than zero.")
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
            self._customer["id"], amt, method=method, account_id=acct_id,
            account_name=acct_name, notes=self.note.text())
        if not ok:
            QMessageBox.warning(self, "Could not record recovery", msg)
            return
        show_toast(self, "Recovery recorded")
        self.amount.setValue(0)
        self.note.clear()
        self._refresh_customers()
        self._sync_customer()
        # printable receipt for the customer
        rok, rmsg, path = self.controller.payment_receipt(pay_id)
        if rok:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(
                self, "Recovery saved",
                "Recovery recorded, but the receipt could not be created:\n" + rmsg)
