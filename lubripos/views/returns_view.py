"""Returns / Refund page (partial or full).

Look up a completed sale by its invoice number, then choose HOW MANY of each
item to return. The chosen quantities are added back to stock and recorded in
the returns ledger (so reports net the refund out). A line can never be
over-returned — its Return box is capped at what is still returnable.

Gated by the 'Void / reverse a sale' privilege.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.sale_controller import SaleController
from ..core.session import current_session

COLUMNS = ["Product", "Sold", "Returned", "Return", "Unit Price", "Refund"]
C_PRODUCT, C_SOLD, C_RETURNED, C_RETURN, C_PRICE, C_REFUND = range(6)


class ReturnsView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SaleController(ctx)
        self._sale: dict | None = None
        self._rows: list[dict] = []   # {sale_item_id, unit_price_minor, spin, refund_item}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel("Returns / Refund")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        lookup = QHBoxLayout()
        self.invoice = QLineEdit()
        self.invoice.setPlaceholderText("Enter invoice number (e.g. INV-000012) and press Enter…")
        self.invoice.setMinimumHeight(32)
        self.invoice.returnPressed.connect(self._fetch)
        fetch_btn = QPushButton("Fetch invoice")
        fetch_btn.clicked.connect(self._fetch)
        lookup.addWidget(self.invoice, 1)
        lookup.addWidget(fetch_btn)
        root.addLayout(lookup)

        self.meta = QLabel("Enter an invoice number to look it up.")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        root.addWidget(self.meta)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(C_PRODUCT, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.all_btn = QPushButton("Return all remaining")
        self.all_btn.setObjectName("Secondary")
        self.all_btn.clicked.connect(self._select_all)
        self.all_btn.setEnabled(False)
        footer.addWidget(self.all_btn)
        footer.addStretch(1)
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700; font-size:15px;")
        footer.addWidget(self.total_lbl)
        self.return_btn = QPushButton("Process return")
        self.return_btn.setObjectName("Success")
        self.return_btn.setMinimumHeight(36)
        self.return_btn.clicked.connect(self._process)
        self.return_btn.setEnabled(False)
        if not current_session.can("sale.void"):
            self.return_btn.setToolTip("You do not have the return/void privilege")
        footer.addWidget(self.return_btn)
        root.addLayout(footer)

    # -- data ---------------------------------------------------------
    def _fetch(self) -> None:
        inv = self.invoice.text().strip()
        if not inv:
            return
        try:
            sale = self.controller.find_by_invoice(inv)
        except Exception:
            sale = None
        if not sale:
            self._clear(f"No invoice found matching '{inv}'.")
            return
        self._sale = sale
        self._populate(sale)

    def _clear(self, message: str) -> None:
        self._sale = None
        self._rows = []
        self.table.setRowCount(0)
        self.total_lbl.setText("")
        self.all_btn.setEnabled(False)
        self.return_btn.setEnabled(False)
        self.meta.setText(message)

    def _populate(self, sale: dict) -> None:
        items = sale.get("items", [])
        self.table.setRowCount(0)
        self.table.setRowCount(len(items))
        self._rows = []
        can = current_session.can("sale.void")
        is_void = sale.get("status") == "void"
        any_returnable = False

        for r, it in enumerate(items):
            sold = it["qty"]
            returned = it.get("returned_qty", 0)
            remaining = sold - returned
            if remaining > 0:
                any_returnable = True

            self.table.setItem(r, C_PRODUCT, QTableWidgetItem(
                it.get("product_name") or "(removed product)"))
            for col, val in ((C_SOLD, sold), (C_RETURNED, returned)):
                cell = QTableWidgetItem(str(val))
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, cell)

            spin = QSpinBox()
            spin.setRange(0, max(0, remaining))
            spin.setValue(0)
            spin.setEnabled(can and not is_void and remaining > 0)
            spin.valueChanged.connect(self._recalc)
            self.table.setCellWidget(r, C_RETURN, spin)

            price = QTableWidgetItem(self.controller.fmt(it["unit_price_minor"]))
            price.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, C_PRICE, price)

            refund_item = QTableWidgetItem(self.controller.fmt(0))
            refund_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, C_REFUND, refund_item)

            self._rows.append({"sale_item_id": it["id"],
                               "unit_price_minor": it["unit_price_minor"],
                               "spin": spin, "refund_item": refund_item})

        status = sale.get("status")
        self.meta.setText(
            f"Invoice {sale.get('invoice_no')}   •   {(sale.get('sale_date') or '')[:16]}"
            f"   •   Cashier: {sale.get('cashier_name') or '-'}"
            f"   •   Total: {self.controller.fmt(sale.get('grand_total_minor', 0))}"
            f"   •   Status: {status}")
        self.all_btn.setEnabled(can and not is_void and any_returnable)
        self._recalc()

    def _select_all(self) -> None:
        for row in self._rows:
            row["spin"].setValue(row["spin"].maximum())

    def _recalc(self) -> None:
        total = 0
        for row in self._rows:
            refund = row["spin"].value() * row["unit_price_minor"]
            row["refund_item"].setText(self.controller.fmt(refund))
            total += refund
        self.total_lbl.setText("Refund:  " + self.controller.fmt(total))
        can = current_session.can("sale.void")
        self.return_btn.setEnabled(can and total > 0)

    def _process(self) -> None:
        if not self._sale:
            return
        lines = [{"sale_item_id": row["sale_item_id"], "qty": row["spin"].value()}
                 for row in self._rows if row["spin"].value() > 0]
        if not lines:
            QMessageBox.information(self, "Nothing selected",
                                    "Set a Return quantity on at least one item.")
            return
        total = sum(r["spin"].value() * r["unit_price_minor"] for r in self._rows)
        confirm = QMessageBox.question(
            self, "Confirm return",
            f"Return the selected items from invoice {self._sale.get('invoice_no')}?\n\n"
            f"Stock will be restored and {self.controller.fmt(total)} refunded. "
            "This cannot be undone.")
        if confirm != QMessageBox.Yes:
            return
        ok, msg, data = self.controller.create_return(self._sale["id"], lines)
        if ok:
            QMessageBox.information(
                self, "Returned",
                f"Return recorded: stock restored and "
                f"{self.controller.fmt(data['refund_minor'])} refunded.")
            self._fetch()   # refresh remaining quantities
        else:
            QMessageBox.warning(self, "Could not return", msg)
