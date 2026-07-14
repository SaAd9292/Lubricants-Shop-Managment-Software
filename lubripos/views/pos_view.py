"""Point of Sale screen.

Workflow: scan a barcode (USB scanner acts as a keyboard) -> product is added
to the cart instantly; or use 'Search product' to add by name. Each cart row
shows the item (with its stock), price, a -/+ quantity stepper, the line total,
and a remove button. Set a discount and a payment method/account, then press
Complete Sale (F2). Completing the sale decrements stock and allocates an
invoice number atomically.

Accessible to both admin and cashier.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QButtonGroup, QComboBox, QDoubleSpinBox,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.sale_controller import SaleController
from ..controllers.payment_account_controller import PaymentAccountController
from ..core import money
from ..core.session import current_session
from ..ui.icons import make_icon
from .product_picker_dialog import ProductPickerDialog
from .sale_receipt_dialog import SaleReceiptDialog

# Cart columns
C_NUM, C_ITEM, C_PRICE, C_QTY, C_TOTAL, C_ACTION = range(6)
_METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _QtyStepper(QWidget):
    """A '- N +' quantity control. Wraps a QSpinBox (min 1, max = stock) with
    the native arrows hidden and flanking - / + buttons, so it reads like the
    counter on a modern POS. Exposes value()/setValue()/maximum()."""

    def __init__(self, value: int, maximum: int, on_change) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.spin = QSpinBox()
        self.spin.setRange(1, max(1, maximum))
        self.spin.setValue(value)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setFixedWidth(44)
        self.spin.valueChanged.connect(on_change)
        minus = QPushButton("−")
        minus.setObjectName("StepBtn")
        minus.setFixedSize(30, 26)
        plus = QPushButton("+")
        plus.setObjectName("StepBtn")
        plus.setFixedSize(30, 26)
        minus.clicked.connect(lambda: self.spin.setValue(max(self.spin.minimum(), self.spin.value() - 1)))
        plus.clicked.connect(lambda: self.spin.setValue(min(self.spin.maximum(), self.spin.value() + 1)))
        lay.addWidget(minus)
        lay.addWidget(self.spin)
        lay.addWidget(plus)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int) -> None:
        self.spin.setValue(v)

    def maximum(self) -> int:
        return self.spin.maximum()


class POSView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SaleController(ctx)
        self.pay_ctl = PaymentAccountController(ctx)
        self._symbol, self._minor_units = self.controller.currency()
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.status.setText(""))
        self._build_ui()
        self._recompute()

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        # ---- left: scan + cart ----
        left = QVBoxLayout()
        left.setSpacing(12)
        title = QLabel("Sale")
        title.setObjectName("PageTitle")
        left.addWidget(title)

        scan_row = QHBoxLayout()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan barcode and press Enter…")
        self.barcode.setMinimumHeight(34)
        self.barcode.returnPressed.connect(self._add_by_barcode)
        search_btn = QPushButton("Search product")
        search_btn.setObjectName("Secondary")
        search_btn.clicked.connect(self._add_by_search)
        scan_row.addWidget(self.barcode, 1)
        scan_row.addWidget(search_btn)
        left.addLayout(scan_row)

        # non-blocking inline status line (replaces interrupting popups)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setMinimumHeight(18)
        left.addWidget(self.status)

        self.cart = QTableWidget(0, 6)
        self.cart.setHorizontalHeaderLabels(
            ["#", "Item", f"Price ({self._symbol})", "Qty", "Line Total", ""])
        self.cart.verticalHeader().setVisible(False)
        self.cart.verticalHeader().setDefaultSectionSize(50)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.cart.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(C_NUM, QHeaderView.Fixed)
        hdr.setSectionResizeMode(C_ITEM, QHeaderView.Stretch)
        for c in (C_PRICE, C_QTY, C_TOTAL, C_ACTION):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        self.cart.setColumnWidth(C_NUM, 38)
        self.cart.setColumnWidth(C_PRICE, 120)
        self.cart.setColumnWidth(C_QTY, 120)
        self.cart.setColumnWidth(C_TOTAL, 120)
        self.cart.setColumnWidth(C_ACTION, 46)
        left.addWidget(self.cart, 1)

        cart_actions = QHBoxLayout()
        clear_btn = QPushButton("Clear cart")
        clear_btn.setObjectName("Secondary")
        clear_btn.clicked.connect(self._clear_cart)
        cart_actions.addStretch(1)
        cart_actions.addWidget(clear_btn)
        left.addLayout(cart_actions)
        root.addLayout(left, 2)

        # ---- right: bill summary + payment ----
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setFixedWidth(360)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(20, 20, 20, 20)
        pl.setSpacing(12)

        pl.addWidget(self._h2("Bill Summary"))
        self.lbl_subtotal = self._kv(pl, "Subtotal")

        disc_row = QHBoxLayout()
        disc_row.addWidget(QLabel("Discount"))
        self.discount = QDoubleSpinBox()
        self.discount.setRange(0, 1_000_000_000)
        self.discount.setDecimals(self._decimals)
        self.discount.setGroupSeparatorShown(True)
        self.discount.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.discount.valueChanged.connect(self._recompute)
        if not current_session.can("sale.discount"):
            self.discount.setEnabled(False)
            self.discount.setToolTip("You do not have the discount privilege")
        disc_row.addStretch(1)
        disc_row.addWidget(self.discount)
        pl.addLayout(disc_row)

        self.tax_row = QWidget()
        _trow = QHBoxLayout(self.tax_row)
        _trow.setContentsMargins(0, 0, 0, 0)
        _trow.addWidget(QLabel("Tax"))
        self.lbl_tax = QLabel("—")
        self.lbl_tax.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        _trow.addStretch(1)
        _trow.addWidget(self.lbl_tax)
        pl.addWidget(self.tax_row)

        line = QFrame(); line.setFrameShape(QFrame.HLine); pl.addWidget(line)
        self.lbl_total = self._kv(pl, "Grand Total", big=True)

        pl.addWidget(self._h2("Payment"))
        # payment method as selectable chips
        self._method_group = QButtonGroup(self)
        self._method_group.setExclusive(True)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for m in _METHODS:
            chip = QPushButton(m)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            if m == "Cash":
                chip.setChecked(True)
            self._method_group.addButton(chip)
            chips.addWidget(chip)
        chips.addStretch(1)
        pl.addLayout(chips)
        self._method_group.buttonClicked.connect(lambda _btn: self._reload_accounts())

        acct_row = QHBoxLayout()
        self.account_label = QLabel("Account")
        self.account = QComboBox()
        acct_row.addWidget(self.account_label)
        acct_row.addStretch(1)
        acct_row.addWidget(self.account)
        pl.addLayout(acct_row)
        self._reload_accounts()

        pl.addStretch(1)

        complete = QPushButton("Complete Sale  (F2)")
        complete.setObjectName("Success")
        complete.setMinimumHeight(40)
        complete.clicked.connect(self._complete)
        pl.addWidget(complete)
        QShortcut(QKeySequence("F2"), self, self._complete)

        root.addWidget(panel)
        self.barcode.setFocus()

    def _h2(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 700; font-size: 15px;")
        return lbl

    def _kv(self, layout: QVBoxLayout, label: str, big: bool = False) -> QLabel:
        row = QHBoxLayout()
        k = QLabel(label)
        if big:
            k.setStyleSheet("font-weight:700; font-size:16px;")
        v = QLabel("—")
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if big:
            v.setStyleSheet("font-weight:700; font-size:20px; color:#16a34a;")
        row.addWidget(k)
        row.addStretch(1)
        row.addWidget(v)
        layout.addLayout(row)
        return v

    def _selected_method(self) -> str:
        btn = self._method_group.checkedButton()
        return btn.text() if btn else "Cash"

    # -- cart ops -----------------------------------------------------
    def _add_by_barcode(self) -> None:
        code = self.barcode.text().strip()
        self.barcode.clear()
        if not code:
            return
        product = self.controller.find_by_barcode(code)
        if product is None:
            self._flash(f"No active product with barcode '{code}'.", error=True)
            return
        self._add_product(product)

    def _add_by_search(self) -> None:
        picker = ProductPickerDialog(
            self.controller.search_products, self.controller.fmt,
            self.controller.categories())
        if picker.exec() and picker.selected:
            self._add_product(picker.selected)
        self.barcode.setFocus()

    def _add_product(self, p: dict) -> None:
        available = int(p.get("stock_qty") or 0)
        if available <= 0:
            self._flash(f"{p['name']} is out of stock.", error=True)
            return
        row = self._find_row(p["id"])
        if row is not None:
            qty_w = self.cart.cellWidget(row, C_QTY)
            if qty_w.value() >= qty_w.maximum():
                self._flash(f"Only {qty_w.maximum()} of '{p['name']}' in stock.", error=True)
                return
            qty_w.setValue(qty_w.value() + 1)
            self._flash(f"{p['name']}  (qty {qty_w.value()})")
            return

        row = self.cart.rowCount()
        self.cart.insertRow(row)

        num = QTableWidgetItem(str(row + 1))
        num.setData(Qt.UserRole, p["id"])  # stash product id
        num.setTextAlignment(Qt.AlignCenter)
        self.cart.setItem(row, C_NUM, num)

        name_lbl = QLabel(
            f"<b>{_esc(p['name'])}</b><br>"
            f"<span style='color:#6b7280; font-size:11px;'>Stock: {available}</span>")
        name_lbl.setContentsMargins(6, 2, 6, 2)
        self.cart.setCellWidget(row, C_ITEM, name_lbl)

        price = QDoubleSpinBox()
        price.setRange(0, 1_000_000_000)
        price.setDecimals(self._decimals)
        price.setGroupSeparatorShown(True)
        price.setButtonSymbols(QAbstractSpinBox.NoButtons)
        price.setValue(float(p["sale_price_minor"]) / self._minor_units)
        price.valueChanged.connect(self._recompute)
        if not current_session.can("sale.edit_price"):
            price.setReadOnly(True)
        self.cart.setCellWidget(row, C_PRICE, price)

        qty = _QtyStepper(1, available, self._recompute)
        self.cart.setCellWidget(row, C_QTY, qty)

        total = QTableWidgetItem("")
        total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cart.setItem(row, C_TOTAL, total)

        rm = QPushButton()
        rm.setObjectName("RemoveBtn")
        rm.setIcon(make_icon("trash", "#dc2626", 16))
        rm.setFixedSize(30, 26)
        rm.setToolTip("Remove item")
        rm.clicked.connect(lambda _=False, pid=p["id"]: self._remove_product(pid))
        rm_cell = QWidget()
        rm_lay = QHBoxLayout(rm_cell)
        rm_lay.setContentsMargins(0, 0, 0, 0)
        rm_lay.addStretch(1)
        rm_lay.addWidget(rm)
        rm_lay.addStretch(1)
        self.cart.setCellWidget(row, C_ACTION, rm_cell)

        self._recompute()
        self._flash(f"Added {p['name']}  ({available} in stock)")

    def _find_row(self, pid: int):
        for r in range(self.cart.rowCount()):
            item = self.cart.item(r, C_NUM)
            if item and item.data(Qt.UserRole) == pid:
                return r
        return None

    def _remove_product(self, pid: int) -> None:
        row = self._find_row(pid)
        if row is not None:
            self.cart.removeRow(row)
            self._recompute()

    def _clear_cart(self) -> None:
        self.cart.setRowCount(0)
        self.discount.setValue(0)
        self._recompute()
        self.barcode.setFocus()

    def _reload_accounts(self) -> None:
        """Populate the account dropdown for the chosen method. Cash has no
        account; a method with none configured shows a hint and the sale then
        records just the method."""
        method = self._selected_method()
        self.account.clear()
        if method == "Cash":
            self.account_label.setEnabled(False)
            self.account.setEnabled(False)
            return
        self.account_label.setEnabled(True)
        accounts = self.pay_ctl.list(method=method, active_only=True)
        if not accounts:
            self.account.addItem("(no accounts - add in Settings)", None)
            self.account.setEnabled(False)
            return
        self.account.setEnabled(True)
        for a in accounts:
            label = a["name"] + (f"  -  {a['account_no']}" if a.get("account_no") else "")
            self.account.addItem(label, a["id"])

    # -- totals -------------------------------------------------------
    def _recompute(self) -> None:
        subtotal = 0
        for r in range(self.cart.rowCount()):
            num_item = self.cart.item(r, C_NUM)
            if num_item is not None:
                num_item.setText(str(r + 1))  # keep row numbers tidy after removals
            qty_w = self.cart.cellWidget(r, C_QTY)
            price_w = self.cart.cellWidget(r, C_PRICE)
            if qty_w is None or price_w is None:
                continue
            unit = money.to_minor(price_w.value(), self._minor_units)
            line = qty_w.value() * unit
            subtotal += line
            self.cart.item(r, C_TOTAL).setText(
                money.format_money(line, self._symbol, self._minor_units))

        discount = money.to_minor(self.discount.value(), self._minor_units)
        discount = min(discount, subtotal)
        net = subtotal - discount

        tax = self.controller.tax_info()
        tax_minor = 0
        tax_text = "—"
        tax_on = bool(tax.get("tax_enabled") and tax.get("tax_rate_bps", 0) > 0)
        if tax_on:
            rate = tax["tax_rate_bps"]
            inclusive = bool(tax.get("tax_inclusive"))
            _, tax_minor = money.apply_tax(net, rate, inclusive=inclusive)
            grand = net if inclusive else net + tax_minor
            label = tax.get("tax_label", "GST")
            suffix = " (incl)" if inclusive else ""
            tax_text = f"{label} {rate/100:.2f}%{suffix}: " \
                       + money.format_money(tax_minor, self._symbol, self._minor_units)
        else:
            grand = net

        # GST/tax off in Settings -> hide the tax line entirely.
        self.tax_row.setVisible(tax_on)
        self.lbl_subtotal.setText(money.format_money(subtotal, self._symbol, self._minor_units))
        self.lbl_tax.setText(tax_text)
        self.lbl_total.setText(money.format_money(grand, self._symbol, self._minor_units))

    # -- checkout -----------------------------------------------------
    def _complete(self) -> None:
        if self.cart.rowCount() == 0:
            self._flash("Cart is empty.", error=True)
            return
        lines = []
        for r in range(self.cart.rowCount()):
            lines.append({
                "product_id": self.cart.item(r, C_NUM).data(Qt.UserRole),
                "qty": self.cart.cellWidget(r, C_QTY).value(),
                "unit_price": self.cart.cellWidget(r, C_PRICE).value(),
            })
        ok, msg, summary = self.controller.checkout(
            lines=lines, discount=self.discount.value(),
            payment_method=self._selected_method(),
            payment_account_id=self.account.currentData(), amount_paid=0,
        )
        if not ok:
            QMessageBox.warning(self, "Sale not completed", msg)
            return
        SaleReceiptDialog(self.ctx, summary["id"]).exec()
        self._clear_cart()
        self._flash(f"Sale {summary['invoice_no']} completed.")

    # -- inline status (non-blocking) ---------------------------------
    def _flash(self, text: str, error: bool = False) -> None:
        color = "#ef4444" if error else "#16a34a"
        self.status.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.status.setText(text)
        self._status_timer.start(2500)
        self.barcode.setFocus()
