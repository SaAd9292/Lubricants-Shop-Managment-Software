"""Returns / Refund page (partial or full).

Look up a completed sale by its invoice number, then choose HOW MANY of each
item to return. The chosen quantities are added back to stock and recorded in
the returns ledger (so reports net the refund out). A line can never be
over-returned — its Return box is capped at what is still returnable.

Gated by the 'Void / reverse a sale' privilege.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QDate, QEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

_RETURN_METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]

from ..app_context import AppContext
from ..controllers.sale_controller import SaleController
from ..core.session import current_session
from .no_receipt_return_dialog import NoReceiptReturnDialog

COLUMNS = ["Product", "Sold", "Returned", "Return", "Unit Price", "Refund"]
C_PRODUCT, C_SOLD, C_RETURNED, C_RETURN, C_PRICE, C_REFUND = range(6)


class ReturnsView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SaleController(ctx)
        self._sale: dict | None = None
        self._rows: list[dict] = []   # {sale_item_id, unit_price_minor, spin, refund_item}
        self._filter_on = False
        self._scan_buf = ""
        self._scan_last = 0.0
        self._build_ui()

    # -- barcode capture ----------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        """While the Returns screen is open, capture receipt-barcode scans
        anywhere on the page — the scanner behaves like a keyboard, so the
        cashier can just scan without first clicking the invoice box. The filter
        is only installed while this screen is visible."""
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None and not self._filter_on:
            app.installEventFilter(self)
            self._filter_on = True

    def hideEvent(self, event) -> None:  # noqa: N802
        app = QApplication.instance()
        if app is not None and self._filter_on:
            app.removeEventFilter(self)
            self._filter_on = False
        super().hideEvent(event)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() != QEvent.KeyPress:
            return super().eventFilter(obj, event)
        # never capture while a dialog is open (e.g. the confirm-return box)
        if QApplication.activeModalWidget() is not None:
            return False
        # If the cashier is actually typing in a text/number box (the invoice box
        # or a return-qty spinner), leave those keystrokes alone.
        fw = QApplication.focusWidget()
        if fw is self.invoice or isinstance(fw, (QAbstractSpinBox, QLineEdit)):
            return False
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            code = self._scan_buf.strip()
            self._scan_buf = ""
            if code:
                self.invoice.setText(code)
                self._fetch()
                return True   # a scan completed — consume the Enter
            return False
        text = event.text()
        if text and text.isprintable() and not text.isspace():
            now = time.monotonic()
            if now - self._scan_last > 0.5:   # a long pause means a new code
                self._scan_buf = ""
            self._scan_buf += text
            self._scan_last = now
            return True   # swallow scan chars so they don't trigger buttons
        return False

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel("Returns / Refund")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        lookup = QHBoxLayout()
        self.invoice = QLineEdit()
        self.invoice.setPlaceholderText("Scan the receipt barcode, or type the invoice number (e.g. INV-000012) and press Enter…")
        self.invoice.setMinimumHeight(32)
        self.invoice.returnPressed.connect(self._fetch)
        fetch_btn = QPushButton("Fetch invoice")
        fetch_btn.clicked.connect(self._fetch)
        self.noreceipt_btn = QPushButton("Return without receipt")
        self.noreceipt_btn.setObjectName("Secondary")
        self.noreceipt_btn.clicked.connect(self._no_receipt_return)
        if not current_session.can("sale.void"):
            self.noreceipt_btn.setToolTip("You do not have the return/void privilege")
        lookup.addWidget(self.invoice, 1)
        lookup.addWidget(fetch_btn)
        lookup.addWidget(self.noreceipt_btn)
        root.addLayout(lookup)

        self.meta = QLabel("Enter an invoice number to look it up.")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        root.addWidget(self.meta)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        # rows carry a "return qty" spin box; keep it from clipping
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(C_PRODUCT, QHeaderView.Stretch)
        # the processing table is a working area, not the main content — cap it
        # so the Returns-history panel below always has room.
        self.table.setMaximumHeight(240)
        root.addWidget(self.table)

        footer = QHBoxLayout()
        self.all_btn = QPushButton("Return all remaining")
        self.all_btn.setObjectName("Secondary")
        self.all_btn.clicked.connect(self._select_all)
        self.all_btn.setEnabled(False)
        footer.addWidget(self.all_btn)
        footer.addSpacing(12)
        footer.addWidget(QLabel("Return date"))
        self.ret_date = QDateEdit()
        self.ret_date.setCalendarPopup(True)
        self.ret_date.setDisplayFormat("dd MMM yyyy")
        self.ret_date.setMaximumDate(QDate.currentDate())
        self.ret_date.setDate(QDate.currentDate())
        self.ret_date.setToolTip("Date to record this return on (back-date if needed)")
        footer.addWidget(self.ret_date)
        footer.addStretch(1)
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700; font-size:15px;")
        footer.addWidget(self.total_lbl)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Secondary")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.clicked.connect(self._abort)
        self.cancel_btn.setEnabled(False)
        footer.addWidget(self.cancel_btn)
        self.return_btn = QPushButton("Process return")
        self.return_btn.setObjectName("Success")
        self.return_btn.setMinimumHeight(36)
        self.return_btn.clicked.connect(self._process)
        self.return_btn.setEnabled(False)
        if not current_session.can("sale.void"):
            self.return_btn.setToolTip("You do not have the return/void privilege")
        footer.addWidget(self.return_btn)
        root.addLayout(footer)

        # ===== Returns history =====================================
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Muted")
        root.addWidget(sep)

        hist_head = QHBoxLayout()
        htitle = QLabel("Returns history")
        htitle.setStyleSheet("font-size:15px;font-weight:700;")
        hist_head.addWidget(htitle)
        hist_head.addStretch(1)
        hist_head.addWidget(QLabel("From"))
        self.h_from = QDateEdit()
        self.h_from.setCalendarPopup(True)
        self.h_from.setDisplayFormat("dd MMM yyyy")
        self.h_from.setDate(QDate.currentDate().addMonths(-1))
        self.h_from.dateChanged.connect(lambda _=None: self._reload_history())
        hist_head.addWidget(self.h_from)
        hist_head.addWidget(QLabel("To"))
        self.h_to = QDateEdit()
        self.h_to.setCalendarPopup(True)
        self.h_to.setDisplayFormat("dd MMM yyyy")
        self.h_to.setDate(QDate.currentDate())
        self.h_to.dateChanged.connect(lambda _=None: self._reload_history())
        hist_head.addWidget(self.h_to)
        self.edit_btn = QPushButton("Edit selected return")
        self.edit_btn.setObjectName("Secondary")
        self.edit_btn.setToolTip("Correct this return's date, refund method or note "
                                 "(to change quantities, reverse it and re-enter)")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.edit_btn.setEnabled(False)
        hist_head.addWidget(self.edit_btn)
        self.reverse_btn = QPushButton("Reverse selected return")
        self.reverse_btn.setObjectName("Secondary")
        self.reverse_btn.setToolTip("Undo the selected return: pull the restocked "
                                    "quantity back and reverse its refund")
        self.reverse_btn.clicked.connect(self._reverse_selected)
        self.reverse_btn.setEnabled(False)
        hist_head.addWidget(self.reverse_btn)
        root.addLayout(hist_head)

        HCOLS = ["Date", "Invoice / Type", "Items", "Refund", "Method", "By"]
        self.history = QTableWidget(0, len(HCOLS))
        self.history.setHorizontalHeaderLabels(HCOLS)
        self.history.verticalHeader().setVisible(False)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history.itemSelectionChanged.connect(self._sync_hist_btns)
        root.addWidget(self.history, 1)

        self._reload_history()

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
        self.cancel_btn.setEnabled(False)
        self.meta.setText(message)

    def _abort(self) -> None:
        """Abort a return in progress: drop the fetched invoice, clear the table
        and totals, and put the cursor back in the invoice box for the next one."""
        self.invoice.clear()
        self._clear("Enter an invoice number to look it up.")
        self.invoice.setFocus()

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
        self.cancel_btn.setEnabled(True)
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
        rdate = self.ret_date.date().toString("yyyy-MM-dd")
        ok, msg, data = self.controller.create_return(
            self._sale["id"], lines, return_date=rdate)
        if ok:
            QMessageBox.information(
                self, "Returned",
                f"Return recorded: stock restored and "
                f"{self.controller.fmt(data['refund_minor'])} refunded.")
            self._fetch()         # refresh remaining quantities
            self._reload_history()
        else:
            QMessageBox.warning(self, "Could not return", msg)

    # -- no-receipt return -------------------------------------------
    def _no_receipt_return(self) -> None:
        """Open the unlinked-return dialog. Still gated by the return/void
        privilege, but no admin-password re-confirm."""
        if not current_session.can("sale.void"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the return/void privilege.")
            return
        dlg = NoReceiptReturnDialog(self.ctx, self.controller, self)
        dlg.exec()
        self._reload_history()


class ReturnEditDialog(QDialog):
    """Edit a return's date, refund method and note (not its quantities)."""

    def __init__(self, detail: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit return")
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        full = (detail.get("return_date_full") or detail.get("date") or "")[:10]
        qd = QDate.fromString(full, "yyyy-MM-dd")
        self.date.setDate(qd if qd.isValid() else QDate.currentDate())
        form.addRow("Return date", self.date)

        self.method = QComboBox()
        self.method.addItems(_RETURN_METHODS)
        cur = (detail.get("method") or "Cash")
        i = self.method.findText(cur)
        self.method.setCurrentIndex(i if i >= 0 else 0)
        form.addRow("Refund via", self.method)

        self.note = QLineEdit(detail.get("notes") or "")
        self.note.setPlaceholderText("Optional note")
        form.addRow("Note", self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {"date": self.date.date().toString("yyyy-MM-dd"),
                "method": self.method.currentText(),
                "notes": self.note.text().strip()}

    # -- returns history ---------------------------------------------
    def _reload_history(self) -> None:
        d_from = self.h_from.date().toString("yyyy-MM-dd")
        d_to = self.h_to.date().toString("yyyy-MM-dd")
        try:
            res = self.controller.returns(date_from=d_from, date_to=d_to)
            rows = res["rows"]
        except Exception:
            rows = []
        self.history.setRowCount(0)
        self.history.setRowCount(len(rows))
        for r, row in enumerate(rows):
            kind = row["invoice"] or "(no receipt)"
            summary = f"{row['units']} item(s)"
            cells = [row["date"], kind, summary,
                     self.controller.fmt(row["refund"]), row["method"], row["by_name"]]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(str(val))
                if c == 0:
                    it.setData(Qt.UserRole, row["id"])
                if c in (2, 3):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.history.setItem(r, c, it)
        self._sync_hist_btns()

    def _sync_hist_btns(self) -> None:
        on = current_session.can("sale.void") and self.history.currentRow() >= 0
        self.edit_btn.setEnabled(on)
        self.reverse_btn.setEnabled(on)

    def _selected_return_id(self):
        row = self.history.currentRow()
        if row < 0:
            return None
        it = self.history.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def _edit_selected(self) -> None:
        if not current_session.can("sale.void"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the return/void privilege.")
            return
        rid = self._selected_return_id()
        if rid is None:
            return
        try:
            detail = self.controller.return_detail(rid)
        except Exception as exc:
            QMessageBox.warning(self, "Could not open", str(exc))
            return
        dlg = ReturnEditDialog(detail, self)
        if dlg.exec() != dlg.Accepted:
            return
        vals = dlg.values()
        ok, msg, _ = self.controller.edit_return(
            rid, return_date=vals["date"], method=vals["method"], notes=vals["notes"])
        if ok:
            self._reload_history()
        else:
            QMessageBox.warning(self, "Could not save", msg)

    def _reverse_selected(self) -> None:
        if not current_session.can("sale.void"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the return/void privilege.")
            return
        row = self.history.currentRow()
        if row < 0:
            return
        it = self.history.item(row, 0)
        rid = it.data(Qt.UserRole) if it else None
        if rid is None:
            return
        refund = self.history.item(row, 3).text()
        kind = self.history.item(row, 1).text()
        confirm = QMessageBox.warning(
            self, "Reverse return",
            f"Reverse this return ({kind}, refund {refund})?\n\n"
            "The restocked quantity will be pulled back off the product(s) and the "
            "refund undone. This cannot itself be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.reverse_return(rid)
        if ok:
            QMessageBox.information(self, "Reversed",
                                    "The return was reversed and stock corrected.")
            self._reload_history()
            if self._sale:
                self._fetch()   # keep the open invoice's remaining quantities fresh
        else:
            QMessageBox.warning(self, "Could not reverse", msg)
