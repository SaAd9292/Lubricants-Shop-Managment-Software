"""Point of Sale screen.

Workflow: scan a barcode (USB scanner acts as a keyboard) -> product is added
to the cart instantly; or use 'Search product' to add by name. Adjust qty and
price per line, set discount/payment, then Complete Sale (F2). Completing the
sale decrements stock and allocates an invoice number atomically.

Accessible to both admin and cashier.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.sale_controller import SaleController
from ..core import money
from .product_picker_dialog import ProductPickerDialog
from .sale_receipt_dialog import SaleReceiptDialog


class POSView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SaleController(ctx)
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

        self.cart = QTableWidget(0, 4)
        self.cart.setHorizontalHeaderLabels(
            ["Product", "Qty", f"Price ({self._symbol})", "Total"]
        )
        self.cart.verticalHeader().setVisible(False)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cart.horizontalHeader().setStretchLastSection(False)
        self.cart.setColumnWidth(0, 280)
        left.addWidget(self.cart, 1)

        cart_actions = QHBoxLayout()
        remove_btn = QPushButton("Remove line")
        remove_btn.setObjectName("Secondary")
        remove_btn.clicked.connect(self._remove_line)
        clear_btn = QPushButton("Clear cart")
        clear_btn.setObjectName("Secondary")
        clear_btn.clicked.connect(self._clear_cart)
        cart_actions.addWidget(remove_btn)
        cart_actions.addWidget(clear_btn)
        cart_actions.addStretch(1)
        left.addLayout(cart_actions)
        root.addLayout(left, 2)

        # ---- right: totals + payment ----
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setFixedWidth(340)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(20, 20, 20, 20)
        pl.setSpacing(12)

        pl.addWidget(self._h2("Summary"))
        self.lbl_subtotal = self._kv(pl, "Subtotal")

        disc_row = QHBoxLayout()
        disc_row.addWidget(QLabel("Discount"))
        self.discount = QDoubleSpinBox()
        self.discount.setRange(0, 1_000_000_000)
        self.discount.setDecimals(self._decimals)
        self.discount.setGroupSeparatorShown(True)
        self.discount.valueChanged.connect(self._recompute)
        disc_row.addStretch(1)
        disc_row.addWidget(self.discount)
        pl.addLayout(disc_row)

        self.lbl_tax = self._kv(pl, "Tax")
        line = QFrame(); line.setFrameShape(QFrame.HLine); pl.addWidget(line)
        self.lbl_total = self._kv(pl, "Grand Total", big=True)

        pl.addWidget(self._h2("Payment"))
        pay_row = QHBoxLayout()
        pay_row.addWidget(QLabel("Method"))
        self.method = QComboBox()
        self.method.addItems(["Cash", "Bank", "EasyPaisa", "JazzCash"])
        pay_row.addStretch(1)
        pay_row.addWidget(self.method)
        pl.addLayout(pay_row)

        pl.addStretch(1)

        complete = QPushButton("Complete Sale  (F2)")
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
            v.setStyleSheet("font-weight:700; font-size:20px;")
        row.addWidget(k)
        row.addStretch(1)
        row.addWidget(v)
        layout.addLayout(row)
        return v

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
        picker = ProductPickerDialog(self.controller.search_products, self.controller.fmt)
        if picker.exec() and picker.selected:
            self._add_product(picker.selected)
        self.barcode.setFocus()

    def _add_product(self, p: dict) -> None:
        row = self._find_row(p["id"])
        if row is not None:
            qty_w = self.cart.cellWidget(row, 1)
            qty_w.setValue(qty_w.value() + 1)
            self._flash(f"{p['name']}  (qty {qty_w.value()})")
            return
        row = self.cart.rowCount()
        self.cart.insertRow(row)
        name_item = QTableWidgetItem(p["name"])
        name_item.setData(Qt.UserRole, p["id"])
        self.cart.setItem(row, 0, name_item)

        qty = QSpinBox(); qty.setRange(1, 1_000_000); qty.setValue(1)
        qty.valueChanged.connect(self._recompute)
        self.cart.setCellWidget(row, 1, qty)

        price = QDoubleSpinBox(); price.setRange(0, 1_000_000_000)
        price.setDecimals(self._decimals); price.setGroupSeparatorShown(True)
        price.setValue(float(p["sale_price_minor"]) / self._minor_units)
        price.valueChanged.connect(self._recompute)
        self.cart.setCellWidget(row, 2, price)

        total = QTableWidgetItem("")
        total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cart.setItem(row, 3, total)
        self._recompute()
        self._flash(f"Added {p['name']}")

    def _find_row(self, pid: int):
        for r in range(self.cart.rowCount()):
            if self.cart.item(r, 0).data(Qt.UserRole) == pid:
                return r
        return None

    def _remove_line(self) -> None:
        r = self.cart.currentRow()
        if r >= 0:
            self.cart.removeRow(r)
            self._recompute()

    def _clear_cart(self) -> None:
        self.cart.setRowCount(0)
        self.discount.setValue(0)
        self._recompute()
        self.barcode.setFocus()

    # -- totals -------------------------------------------------------
    def _recompute(self) -> None:
        subtotal = 0
        for r in range(self.cart.rowCount()):
            qty_w = self.cart.cellWidget(r, 1)
            price_w = self.cart.cellWidget(r, 2)
            if qty_w is None or price_w is None:
                continue
            unit = money.to_minor(price_w.value(), self._minor_units)
            line = qty_w.value() * unit
            subtotal += line
            self.cart.item(r, 3).setText(money.format_money(line, self._symbol, self._minor_units))

        discount = money.to_minor(self.discount.value(), self._minor_units)
        discount = min(discount, subtotal)
        net = subtotal - discount

        tax = self.controller.tax_info()
        tax_minor = 0
        tax_text = "—"
        if tax.get("tax_enabled") and tax.get("tax_rate_bps", 0) > 0:
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
                "product_id": self.cart.item(r, 0).data(Qt.UserRole),
                "qty": self.cart.cellWidget(r, 1).value(),
                "unit_price": self.cart.cellWidget(r, 2).value(),
            })
        ok, msg, summary = self.controller.checkout(
            lines=lines, discount=self.discount.value(),
            payment_method=self.method.currentText(), amount_paid=0,
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
