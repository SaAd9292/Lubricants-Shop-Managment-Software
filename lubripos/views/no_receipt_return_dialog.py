"""No-receipt return dialog.

A customer brings goods back with no receipt / invoice to price against, so the
operator picks the product(s) by name, sets the quantity, and decides the refund
amount for each line (there is no original sale to look it up from). Stock is
restored and the refund is recorded against no sale (sale_returns.sale_id NULL).

Opening this dialog requires the return/void privilege (the same gate as a
normal receipt return). The refund method (Cash / Bank / EasyPaisa / JazzCash)
is recorded so the Daily Sales Report only deducts cash refunds from
cash-in-hand.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QDate, QEvent, QStringListModel
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QCompleter, QDateEdit, QDialog,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core import money
from ..controllers.sale_controller import SaleController

CART_COLS = ["Product", "Qty", "Refund", "Line total", ""]

# (display label, stored method value)
REFUND_METHODS = [
    ("Cash", "Cash"),
    ("Bank / transfer", "Bank"),
    ("EasyPaisa", "EasyPaisa"),
    ("JazzCash", "JazzCash"),
    ("Credit to customer account", "Ledger"),
]


class NoReceiptReturnDialog(QDialog):
    """Build one or more unlinked return lines, then record them in a single
    return."""

    def __init__(self, ctx: AppContext, controller: SaleController,
                 parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.controller = controller
        self._cart: list[dict] = []          # {product_id, name, qty, refund_minor}
        self._name_index: dict[str, dict] = {}
        self.result_data: dict | None = None
        self.setWindowTitle("Return without receipt")
        self.setMinimumWidth(640)
        self._build_ui()
        self._refresh_products()

    # -- ui -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        hint = QLabel(
            "No receipt to price against — pick the product, set the quantity, "
            "and enter the refund you are giving for that line. Stock is restored "
            "and the refund is recorded.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # Product (type-ahead)
        self.prod = QLineEdit()
        self.prod.setPlaceholderText("Type product name…")
        self._suggest = QCompleter(self)
        self._suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._suggest.setFilterMode(Qt.MatchContains)
        self._suggest.setCompletionMode(QCompleter.PopupCompletion)
        self._suggest.setMaxVisibleItems(10)
        self.prod.setCompleter(self._suggest)
        self._suggest.activated[str].connect(self._on_pick)
        self.prod.installEventFilter(self)
        form.addRow("Product", self.prod)

        # Qty — big +/- buttons so it's usable by touch/mouse without typing
        self.qty = QSpinBox()
        self.qty.setRange(1, 1_000_000)
        self.qty.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        self.qty.setMinimumHeight(34)
        self.qty.valueChanged.connect(self._sync_refund_default)
        form.addRow("Qty", self.qty)

        # Refund (total for this line)
        sym, _ = self.controller.currency()
        self.refund = QDoubleSpinBox()
        self.refund.setRange(0, 100_000_000)
        self.refund.setDecimals(2)
        self.refund.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.refund.setPrefix(f"{sym} ")
        add_row = QHBoxLayout()
        add_row.addWidget(self.refund, 1)
        add_btn = QPushButton("Add item")
        add_btn.clicked.connect(self._add_line)
        add_row.addWidget(add_btn)
        add_wrap = QWidget(); add_wrap.setLayout(add_row)
        form.addRow("Refund (line)", add_wrap)
        root.addLayout(form)

        # cart of lines
        self.cart = QTableWidget(0, len(CART_COLS))
        self.cart.setHorizontalHeaderLabels(CART_COLS)
        self.cart.verticalHeader().setVisible(False)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cart.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cart.setColumnWidth(4, 40)
        self.cart.cellClicked.connect(self._on_cell)
        root.addWidget(self.cart, 1)

        # method + reason
        mrow = QFormLayout()
        mrow.setHorizontalSpacing(16)
        self.method = QComboBox()
        for label, value in REFUND_METHODS:
            self.method.addItem(label, value)
        self.method.currentIndexChanged.connect(self._on_method_changed)
        mrow.addRow("Refund via", self.method)

        # Customer (only needed when the refund is credited to an account)
        self.cust = QLineEdit()
        self.cust.setPlaceholderText("Customer (required to credit the account)")
        self._cust_index: dict[str, int] = {}
        self._cust_completer = QCompleter(self)
        self._cust_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._cust_completer.setFilterMode(Qt.MatchContains)
        self._cust_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.cust.setCompleter(self._cust_completer)
        self._refresh_customers()
        self._cust_label = QLabel("Customer")
        mrow.addRow(self._cust_label, self.cust)
        self._cust_row_widgets = (self._cust_label, self.cust)
        self.ret_date = QDateEdit()
        self.ret_date.setCalendarPopup(True)
        self.ret_date.setDisplayFormat("dd MMM yyyy")
        self.ret_date.setMaximumDate(QDate.currentDate())
        self.ret_date.setDate(QDate.currentDate())
        mrow.addRow("Return date", self.ret_date)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason / note (optional)")
        mrow.addRow("Reason", self.reason)
        root.addLayout(mrow)

        # total + actions
        foot = QHBoxLayout()
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700; font-size:15px;")
        foot.addWidget(self.total_lbl)
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.ok_btn = QPushButton("Record return")
        self.ok_btn.setObjectName("Success")
        self.ok_btn.setMinimumHeight(36)
        self.ok_btn.clicked.connect(self._process)
        self.ok_btn.setEnabled(False)
        foot.addWidget(self.ok_btn)
        root.addLayout(foot)

        self._update_total()
        self._on_method_changed()
        self.prod.setFocus()

    def _refresh_customers(self) -> None:
        try:
            rows = self.controller.search_customers("", 100000)
        except TypeError:
            rows = self.controller.search_customers("")
        except Exception:
            rows = []
        self._cust_index = {}
        names: list[str] = []
        for c in rows:
            key = (c.get("name") or "").lower()
            if key and key not in self._cust_index:
                self._cust_index[key] = c["id"]
                names.append(c["name"])
        self._cust_completer.setModel(QStringListModel(names, self._cust_completer))

    def _on_method_changed(self) -> None:
        is_ledger = self.method.currentData() == "Ledger"
        for w in self._cust_row_widgets:
            w.setVisible(is_ledger)

    # -- product lookup ----------------------------------------------
    def _refresh_products(self) -> None:
        try:
            rows = self.controller.search_products("", None, 100000)
        except TypeError:
            rows = self.controller.search_products("")
        self._name_index = {}
        names: list[str] = []
        for p in rows:
            key = (p["name"] or "").lower()
            if key and key not in self._name_index:
                self._name_index[key] = p
                names.append(p["name"])
        self._suggest.setModel(QStringListModel(names, self._suggest))

    def _current_product(self) -> dict | None:
        return self._name_index.get(self.prod.text().strip().lower())

    def _mu(self) -> int:
        _, mu = self.controller.currency()
        return mu or 100

    def _on_pick(self, text: str) -> None:
        p = self._name_index.get((text or "").strip().lower())
        if p:
            self._sync_refund_default()
            self.qty.setFocus()
            self.qty.selectAll()

    def _sync_refund_default(self) -> None:
        """Default the line refund to the product's current sale price × qty. The
        operator can override it — there is no receipt, so this is only a hint."""
        p = self._current_product()
        if p is None:
            return
        sp = p.get("sale_price_minor") or 0
        self.refund.setValue(sp * int(self.qty.value()) / self._mu())

    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if (obj is self.prod and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            if self._current_product() is not None:
                self._sync_refund_default()
                self.qty.setFocus()
                self.qty.selectAll()
                return True
        return super().eventFilter(obj, event)

    # -- cart ---------------------------------------------------------
    def _add_line(self) -> None:
        p = self._current_product()
        if p is None:
            QMessageBox.information(self, "Pick a product",
                                    "Choose a product from the list first.")
            self.prod.setFocus()
            return
        mu = self._mu()
        self._cart.append({
            "product_id": p["id"], "name": p["name"],
            "qty": int(self.qty.value()),
            "refund_minor": money.to_minor(self.refund.value(), mu),
        })
        self._render_cart()
        self._update_total()
        self.prod.clear()
        self.qty.setValue(1)
        self.refund.setValue(0)
        self.prod.setFocus()

    def _render_cart(self) -> None:
        self.cart.setRowCount(len(self._cart))
        for r, ln in enumerate(self._cart):
            cells = [
                ln["name"], str(ln["qty"]),
                self.controller.fmt(ln["refund_minor"]),
                self.controller.fmt(ln["refund_minor"]), "✕",
            ]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(Qt.red)
                self.cart.setItem(r, c, item)

    def _on_cell(self, row: int, col: int) -> None:
        if col == len(CART_COLS) - 1 and 0 <= row < len(self._cart):
            self._cart.pop(row)
            self._render_cart()
            self._update_total()

    def _total_minor(self) -> int:
        return sum(ln["refund_minor"] for ln in self._cart)

    def _update_total(self) -> None:
        self.total_lbl.setText("Refund:  " + self.controller.fmt(self._total_minor()))
        self.ok_btn.setEnabled(bool(self._cart))

    # -- process ------------------------------------------------------
    def _process(self) -> None:
        if not self._cart:
            return
        total = self._total_minor()
        method = self.method.currentData()
        credit_customer_id = None
        if method == "Ledger":
            credit_customer_id = self._cust_index.get(self.cust.text().strip().lower())
            if credit_customer_id is None:
                QMessageBox.information(
                    self, "Pick a customer",
                    "To credit the refund to an account, choose a saved customer.")
                self.cust.setFocus()
                return
        how = ("credited to the customer's account" if credit_customer_id
               else f"refunded via {method}")
        confirm = QMessageBox.question(
            self, "Confirm return",
            f"Record a no-receipt return of {len(self._cart)} line(s)?\n\n"
            f"Stock will be restored and {self.controller.fmt(total)} {how}. "
            "This cannot be undone.")
        if confirm != QMessageBox.Yes:
            return
        lines = [{"product_id": ln["product_id"], "qty": ln["qty"],
                  "refund": ln["refund_minor"] / self._mu()} for ln in self._cart]
        ok, msg, data = self.controller.create_no_receipt_return(
            lines=lines, method=method, notes=self.reason.text().strip(),
            return_date=self.ret_date.date().toString("yyyy-MM-dd"),
            credit_customer_id=credit_customer_id)
        if ok:
            self.result_data = data
            QMessageBox.information(
                self, "Return recorded",
                f"Stock restored and {self.controller.fmt(data['refund_minor'])} "
                f"refunded via {method}.")
            self.accept()
        else:
            QMessageBox.warning(self, "Could not record return", msg)
