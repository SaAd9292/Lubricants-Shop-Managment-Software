"""Purchases page: purchase history + create new purchase + view details."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.session import current_session
from ..reports.report_exporter import to_pdf
from ..ui.widgets import DataTable
from ..controllers.purchase_controller import PurchaseController
from .new_purchase_dialog import NewPurchaseDialog
from .purchase_return_dialog import PurchaseReturnDialog
from .security_prompt import require_admin_password

PAGE_SIZE = 25
COLUMNS = ["Date", "Supplier", "Lines", "Total Qty", "Total", "Invoice #"]


class PurchasesView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = PurchaseController(ctx)
        self._page = 0
        self._total = 0
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Purchases")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        if current_session.is_admin:
            ret_btn = QPushButton("Return to supplier")
            ret_btn.setObjectName("Secondary")
            ret_btn.setToolTip("Send goods back to a supplier (reduces stock and "
                               "what you owe them). No cash moves.")
            ret_btn.clicked.connect(self._return_to_supplier)
            header.addWidget(ret_btn)
            rets_btn = QPushButton("Supplier returns")
            rets_btn.setObjectName("Secondary")
            rets_btn.setToolTip("List all goods returned to suppliers; edit or "
                                "delete one")
            rets_btn.clicked.connect(self._open_supplier_returns)
            header.addWidget(rets_btn)
        new_btn = QPushButton("+ New Purchase")
        new_btn.clicked.connect(self._new_purchase)
        header.addWidget(new_btn)
        root.addLayout(header)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Supplier:"))
        self.f_supplier = QComboBox()
        self.f_supplier.addItem("All suppliers", None)
        for s in self.controller.active_suppliers():
            self.f_supplier.addItem(s["name"], s["id"])
        self.f_supplier.currentIndexChanged.connect(self._reset_and_reload)
        filters.addWidget(self.f_supplier)

        self.f_bydate = QCheckBox("By date")
        self.f_bydate.stateChanged.connect(self._on_date_toggle)
        self.f_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.f_to = QDateEdit(QDate.currentDate())
        for de in (self.f_from, self.f_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setEnabled(False)
            de.dateChanged.connect(self._reset_and_reload)
        filters.addWidget(self.f_bydate)
        filters.addWidget(QLabel("From:"))
        filters.addWidget(self.f_from)
        filters.addWidget(QLabel("To:"))
        filters.addWidget(self.f_to)
        filters.addStretch(1)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = ('No purchases yet\n'
                                   'Click "+ New Purchase" to record incoming stock.')
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._view_details)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        view_btn = QPushButton("View details")
        view_btn.setObjectName("Secondary")
        view_btn.clicked.connect(self._view_details)
        footer.addWidget(view_btn)
        if current_session.is_admin:
            edit_btn = QPushButton("Edit purchase")
            edit_btn.setObjectName("Secondary")
            edit_btn.setToolTip("Edit the supplier, date, bill no, note or amount "
                                "paid (to change items, delete and re-enter)")
            edit_btn.clicked.connect(self._edit_selected)
            footer.addWidget(edit_btn)
            self.del_btn = QPushButton("Delete purchase")
            self.del_btn.setObjectName("Danger")
            self.del_btn.clicked.connect(self._delete_selected)
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
    def _on_date_toggle(self) -> None:
        on = self.f_bydate.isChecked()
        self.f_from.setEnabled(on)
        self.f_to.setEnabled(on)
        self._reset_and_reload()

    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        date_from = date_to = None
        if self.f_bydate.isChecked():
            date_from = self.f_from.date().toString("yyyy-MM-dd")
            date_to = self.f_to.date().toString("yyyy-MM-dd")
        result = self.controller.list(
            supplier_id=self.f_supplier.currentData(),
            date_from=date_from,
            date_to=date_to,
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
        )
        self._total = result["total"]
        self._populate(result["rows"])
        self._update_pagination()

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            values = [
                (p.get("purchase_date") or "")[:16],
                p.get("supplier_name") or "—",
                str(p.get("line_count", 0)),
                str(p.get("total_qty", 0)),
                self.controller.fmt(p["total_minor"]),
                p.get("supplier_invoice_no") or "",
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, p["id"])
                self.table.setItem(r, c, item)

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} purchases)")
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

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    # -- actions ------------------------------------------------------
    def _new_purchase(self) -> None:
        if NewPurchaseDialog(self.controller).exec():
            self._reset_and_reload()

    def _return_to_supplier(self) -> None:
        # prefill the supplier from the selected purchase row, if any
        supplier_id = None
        pid = self._selected_id()
        if pid is not None:
            try:
                supplier_id = self.controller.get(pid).get("supplier_id")
            except Exception:
                supplier_id = None
        if PurchaseReturnDialog(self.controller, supplier_id=supplier_id).exec():
            self._reset_and_reload()

    def _open_supplier_returns(self) -> None:
        SupplierReturnsDialog(self.controller, self.ctx, self).exec()
        self._reset_and_reload()      # stock/payables may have changed

    def _view_details(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        data = self.controller.get(pid)
        PurchaseDetailDialog(data, self.controller.fmt, self.ctx).exec()

    def _edit_selected(self) -> None:
        pid = self._selected_id()
        if pid is None:
            QMessageBox.information(self, "Select a purchase", "Please select a row first.")
            return
        data = self.controller.get(pid)
        dlg = PurchaseEditDialog(self.controller, data)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        ok, msg, _ = self.controller.edit(
            pid, supplier_id=v["supplier_id"], purchase_date=v["date"],
            supplier_invoice_no=v["invoice_no"], notes=v["notes"],
            amount_paid=v["amount_paid"])
        if ok:
            self._reset_and_reload()
        else:
            QMessageBox.warning(self, "Could not save", msg)

    def _delete_selected(self) -> None:
        pid = self._selected_id()
        if pid is None:
            QMessageBox.information(self, "Select a purchase", "Please select a row first.")
            return
        confirm = QMessageBox.warning(
            self, "Delete purchase",
            "Permanently delete this purchase? The stock it added will be "
            "removed, and its balance owed to the supplier is reversed. This "
            "cannot be undone.\n\nIf any of these items were already sold, the "
            "delete will be refused.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        if not require_admin_password(self, self.ctx):
            return
        ok, msg, _ = self.controller.delete(pid)
        if ok:
            self._reset_and_reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)


class PurchaseDetailDialog(QDialog):
    def __init__(self, purchase: dict, fmt_fn, ctx: AppContext | None = None) -> None:
        super().__init__()
        self._fmt = fmt_fn
        self._ctx = ctx
        self._purchase = purchase
        self.setWindowTitle(f"Purchase #{purchase['id']}")
        # a normal OS window: minimise / maximise / resize
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(620, 460)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        meta = QLabel(
            f"<b>Supplier:</b> {purchase.get('supplier_name') or '—'}<br>"
            f"<b>Date:</b> {(purchase.get('purchase_date') or '')[:16]}<br>"
            f"<b>Invoice #:</b> {purchase.get('supplier_invoice_no') or '—'}<br>"
            f"<b>Notes:</b> {purchase.get('notes') or '—'}"
        )
        meta.setTextFormat(Qt.RichText)
        root.addWidget(meta)

        items = purchase.get("items", [])
        table = QTableWidget(len(items), 5)
        table.setHorizontalHeaderLabels(
            ["Product", "Qty", "Unit cost", "Disc", "Line total"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for r, it in enumerate(items):
            d = it.get("discount_minor", 0) or 0
            cells = [
                it.get("product_name") or "(removed product)",
                str(it["qty"]),
                self._fmt(it["unit_cost_minor"]),
                ("− " + self._fmt(d)) if d else "—",
                self._fmt(it["line_total_minor"]),
            ]
            for c, val in enumerate(cells):
                cell = QTableWidgetItem(val)
                if c in (1, 2, 3, 4):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, cell)
        root.addWidget(table, 1)

        # itemised totals: gross subtotal -> line discounts -> bill discount -> total
        gross = sum(it["qty"] * it["unit_cost_minor"] for it in items)
        line_disc = sum((it.get("discount_minor", 0) or 0) for it in items)
        bill_disc = purchase.get("discount_minor", 0) or 0
        adv_tax = purchase.get("tax_minor", 0) or 0
        lines = [f"Subtotal (before discount):&nbsp;&nbsp; {self._fmt(gross)}"]
        if line_disc:
            lines.append(f"Line discounts:&nbsp;&nbsp; − {self._fmt(line_disc)}")
        if bill_disc:
            lines.append(f"Bill discount:&nbsp;&nbsp; − {self._fmt(bill_disc)}")
        if adv_tax:
            lines.append(f"Advance tax:&nbsp;&nbsp; + {self._fmt(adv_tax)}")
        lines.append(f"<b>Total:&nbsp;&nbsp; {self._fmt(purchase['total_minor'])}</b>")
        summary = QLabel("<br>".join(lines))
        summary.setTextFormat(Qt.RichText)
        summary.setAlignment(Qt.AlignRight)
        summary.setStyleSheet("font-size: 14px;")
        root.addWidget(summary)

        btns = QHBoxLayout()
        self.print_btn = QPushButton("Print / PDF")
        self.print_btn.setObjectName("Secondary")
        self.print_btn.clicked.connect(self._print)
        self.print_btn.setEnabled(ctx is not None)
        btns.addWidget(self.print_btn)
        btns.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        root.addLayout(btns)

    def _report(self) -> dict:
        """A purchase 'voucher' report: header meta in the subtitle, one row per
        line, and the gross→discount→tax→total breakdown in the summary — the same
        shape the shared PDF/Excel exporter already knows how to render."""
        p = self._purchase
        items = p.get("items", [])
        rows = [{
            "product": it.get("product_name") or "(removed product)",
            "qty": it["qty"],
            "unit_cost": it["unit_cost_minor"],
            "disc": (it.get("discount_minor", 0) or 0),
            "line_total": it["line_total_minor"],
        } for it in items]
        gross = sum(it["qty"] * it["unit_cost_minor"] for it in items)
        line_disc = sum((it.get("discount_minor", 0) or 0) for it in items)
        bill_disc = p.get("discount_minor", 0) or 0
        adv_tax = p.get("tax_minor", 0) or 0
        summary = [{"label": "Subtotal (before discount)", "value": gross, "money": True}]
        if line_disc:
            summary.append({"label": "Line discounts", "value": -line_disc, "money": True})
        if bill_disc:
            summary.append({"label": "Bill discount", "value": -bill_disc, "money": True})
        if adv_tax:
            summary.append({"label": "Advance tax", "value": adv_tax, "money": True})
        summary.append({"label": "Total", "value": p["total_minor"], "money": True})
        return {
            "key": "purchase", "title": f"Purchase #{p['id']}",
            "subtitle": (f"Supplier: {p.get('supplier_name') or '—'}   ·   "
                         f"Date: {(p.get('purchase_date') or '')[:16]}   ·   "
                         f"Invoice #: {p.get('supplier_invoice_no') or '—'}"),
            "orientation": "portrait",
            "columns": [
                {"key": "product", "label": "Product"},
                {"key": "qty", "label": "Qty", "align": "right"},
                {"key": "unit_cost", "label": "Unit cost", "align": "right", "money": True},
                {"key": "disc", "label": "Disc", "align": "right", "money": True},
                {"key": "line_total", "label": "Line total", "align": "right", "money": True},
            ],
            "rows": rows, "summary": summary,
        }

    def _print(self) -> None:
        if self._ctx is None:
            return
        company = self._ctx.company.get_company()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            path = to_pdf(self._report(), company, os.path.join(
                tempfile.gettempdir(),
                f"purchase_{self._purchase['id']}_{stamp}.pdf"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            QMessageBox.warning(self, "Print failed", str(exc))


class PurchaseEditDialog(QDialog):
    """Edit a purchase's header: supplier, date, bill no, note, amount paid.
    Line items aren't editable here (they moved stock) — delete + re-enter for
    those."""

    def __init__(self, controller: PurchaseController, data: dict) -> None:
        super().__init__()
        self.controller = controller
        self._updating = True
        self._total_minor = int(data.get("total_minor") or 0)
        # line subtotal (net of per-line discounts) is the base the bill
        # discount/tax adjust: subtotal = total + discount - tax
        self._subtotal_minor = (self._total_minor
                                + int(data.get("discount_minor") or 0)
                                - int(data.get("tax_minor") or 0))
        self.setWindowTitle("Edit purchase")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        sym, self._mu = controller.currency()
        self._sym = sym
        self._decimals = max(0, len(str(self._mu or 100)) - 1)
        form.addRow("Subtotal", QLabel(controller.fmt(self._subtotal_minor)))

        self.bill_disc = QDoubleSpinBox()
        self.bill_disc.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.bill_disc.setDecimals(self._decimals)
        self.bill_disc.setRange(0, self._subtotal_minor / (self._mu or 100))
        self.bill_disc.setPrefix(f"{sym} ")
        self.bill_disc.setValue((data.get("discount_minor") or 0) / (self._mu or 100))
        self.bill_disc.valueChanged.connect(self._recompute)
        form.addRow("Bill discount", self.bill_disc)

        self.adv_tax = QDoubleSpinBox()
        self.adv_tax.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.adv_tax.setDecimals(self._decimals)
        self.adv_tax.setRange(0, 1_000_000_000)
        self.adv_tax.setPrefix(f"{sym} ")
        self.adv_tax.setToolTip("Advance / withholding tax — actual amount, added to the bill.")
        self.adv_tax.setValue((data.get("tax_minor") or 0) / (self._mu or 100))
        self.adv_tax.valueChanged.connect(self._recompute)
        form.addRow("Advance tax", self.adv_tax)

        self.total_lbl = QLabel(controller.fmt(self._total_minor))
        self.total_lbl.setStyleSheet("font-weight: 700;")
        form.addRow("Total", self.total_lbl)

        self.supplier = QComboBox()
        self.supplier.addItem("(no supplier)", None)
        want = data.get("supplier_id")
        sel = 0
        try:
            sups = controller.active_suppliers()
        except Exception:
            sups = []
        for i, s in enumerate(sups, start=1):
            self.supplier.addItem(s["name"], s["id"])
            if s["id"] == want:
                sel = i
        self.supplier.setCurrentIndex(sel)
        form.addRow("Supplier", self.supplier)

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        qd = QDate.fromString((data.get("purchase_date") or "")[:10], "yyyy-MM-dd")
        self.date.setDate(qd if qd.isValid() else QDate.currentDate())
        form.addRow("Date", self.date)

        self.invoice = QLineEdit(data.get("supplier_invoice_no") or "")
        self.invoice.setPlaceholderText("Supplier's bill / invoice no")
        form.addRow("Bill no", self.invoice)

        self.paid = QDoubleSpinBox()
        self.paid.setMaximum(self._total_minor / (self._mu or 100))
        self.paid.setDecimals(2)
        self.paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.paid.setPrefix(f"{sym} ")
        self.paid.setValue((data.get("amount_paid_minor") or 0) / (self._mu or 100))
        self.paid.setToolTip("How much has been paid to the supplier. Less than "
                             "the total leaves a balance owed (needs a supplier).")
        form.addRow("Amount paid", self.paid)

        self.notes = QLineEdit(data.get("notes") or "")
        form.addRow("Note", self.notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._updating = False

    def _recompute(self) -> None:
        """Recompute the total as subtotal − bill discount + advance tax and keep
        the amount-paid cap in step (it can never exceed the total)."""
        if self._updating:
            return
        mu = self._mu or 100
        disc = round(self.bill_disc.value() * mu)
        tax = round(self.adv_tax.value() * mu)
        self._total_minor = self._subtotal_minor - disc + tax
        self.total_lbl.setText(self.controller.fmt(self._total_minor))
        # if the paid amount now exceeds the total, pull it down to the total
        cap = self._total_minor / mu
        if self.paid.value() > cap:
            self.paid.setValue(cap)
        self.paid.setMaximum(cap)

    def values(self) -> dict:
        return {"supplier_id": self.supplier.currentData(),
                "date": self.date.date().toString("yyyy-MM-dd"),
                "invoice_no": self.invoice.text().strip(),
                "amount_paid": self.paid.value(),
                "discount": self.bill_disc.value(),
                "tax": self.adv_tax.value(),
                "notes": self.notes.text().strip()}


class SupplierReturnsDialog(QDialog):
    """History of goods returned to suppliers (debit notes), with a date filter,
    View items, Edit (date/note) and Delete (reverse — restores stock & payable).
    A resizable window like the other history dialogs."""

    _COLS = ["Date", "Supplier", "Lines", "Total", "Note"]

    def __init__(self, controller: PurchaseController, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.ctx = ctx
        self.setWindowTitle("Supplier returns")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(760, 440)
        self.resize(860, 560)
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.all_dates = QCheckBox("All dates")
        self.all_dates.setChecked(True)
        self.all_dates.stateChanged.connect(self._on_toggle)
        bar.addWidget(self.all_dates)
        bar.addWidget(QLabel("From"))
        self.d_from = QDateEdit()
        self.d_from.setCalendarPopup(True)
        self.d_from.setDisplayFormat("dd MMM yyyy")
        self.d_from.setDate(QDate.currentDate().addMonths(-3))
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
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700;")
        bar.addWidget(self.total_lbl)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._sync_btns)
        self.table.doubleClicked.connect(lambda: self._view())
        root.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.view_btn = QPushButton("View items")
        self.view_btn.setObjectName("Secondary")
        self.view_btn.clicked.connect(self._view)
        self.view_btn.setEnabled(False)
        self.edit_btn = QPushButton("Edit selected")
        self.edit_btn.setObjectName("Secondary")
        self.edit_btn.setToolTip("Correct the return's date or note")
        self.edit_btn.clicked.connect(self._edit)
        self.edit_btn.setEnabled(False)
        self.del_btn = QPushButton("Delete selected")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.setToolTip("Reverse this return: stock comes back and the "
                                "supplier balance goes back up")
        self.del_btn.clicked.connect(self._delete)
        self.del_btn.setEnabled(False)
        btns.addWidget(self.view_btn)
        btns.addWidget(self.edit_btn)
        btns.addWidget(self.del_btn)
        btns.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        root.addLayout(btns)

        self._reload()

    def _on_toggle(self) -> None:
        on = not self.all_dates.isChecked()
        self.d_from.setEnabled(on)
        self.d_to.setEnabled(on)
        self._reload()

    def _reload(self) -> None:
        kw = {}
        if not self.all_dates.isChecked():
            kw["date_from"] = self.d_from.date().toString("yyyy-MM-dd")
            kw["date_to"] = self.d_to.date().toString("yyyy-MM-dd")
        try:
            data = self.controller.list_returns(**kw)
            rows = data["rows"]
        except Exception:
            rows, data = [], {"total": 0}
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [row["date"], row["supplier_name"], str(row["lines"]),
                     self.controller.fmt(row["total_minor"]), row.get("notes") or ""]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(str(val))
                if c == 0:
                    it.setData(Qt.UserRole, row["id"])
                if c in (2, 3):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        self.total_lbl.setText(
            f"{len(rows)} return(s)  ·  total {self.controller.fmt(data['total'])}")
        self._sync_btns()

    def _sync_btns(self) -> None:
        sel = self._selected_id() is not None
        self.view_btn.setEnabled(sel)
        self.edit_btn.setEnabled(sel and current_session.can("record.edit"))
        self.del_btn.setEnabled(sel and current_session.can("record.delete"))

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def _view(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        try:
            d = self.controller.get_return(rid)
        except Exception as exc:
            QMessageBox.warning(self, "Could not open", str(exc))
            return
        lines = "\n".join(
            f"  • {it['product_name']}   ×{it['qty']}   @ "
            f"{self.controller.fmt(it['unit_cost_minor'])}   = "
            f"{self.controller.fmt(it['line_total_minor'])}"
            for it in d.get("items", []))
        QMessageBox.information(
            self, f"Return to {d.get('supplier_name')}",
            f"Date: {(d.get('return_date') or '')[:16]}\n"
            f"Supplier: {d.get('supplier_name')}\n"
            f"Note: {d.get('notes') or '—'}\n\nItems:\n{lines}\n\n"
            f"Total: {self.controller.fmt(d.get('total_minor') or 0)}")

    def _edit(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        if not current_session.can("record.edit"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the Edit records privilege.")
            return
        try:
            d = self.controller.get_return(rid)
        except Exception as exc:
            QMessageBox.warning(self, "Could not open", str(exc))
            return
        dlg = _ReturnEditDialog(self.controller, d, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        ok, msg, _ = self.controller.edit_return(
            rid, return_date=v["date"] + " 12:00:00", notes=v["notes"])
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not save", msg)

    def _delete(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        if not current_session.can("record.delete"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the Delete/reverse privilege.")
            return
        row = self.table.currentRow()
        who = self.table.item(row, 1).text()
        amt = self.table.item(row, 3).text()
        confirm = QMessageBox.warning(
            self, "Delete return",
            f"Delete this return of {amt} to {who}?\n\n"
            "The returned stock comes back and what you owe the supplier goes "
            "back up. This cannot itself be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.reverse_return(rid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)


class _ReturnEditDialog(QDialog):
    """Edit a supplier return's date / note (items are read-only — reverse and
    re-enter to change quantities)."""

    def __init__(self, controller: PurchaseController, data: dict, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(f"Edit return — {data.get('supplier_name')}")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        qd = QDate.fromString((data.get("return_date") or "")[:10], "yyyy-MM-dd")
        self.date.setDate(qd if qd.isValid() else QDate.currentDate())
        form.addRow("Return date", self.date)

        self.notes = QLineEdit(data.get("notes") or "")
        form.addRow("Note", self.notes)
        root.addLayout(form)

        items = QTableWidget(0, 3)
        items.setHorizontalHeaderLabels(["Product", "Qty", "Line total"])
        items.verticalHeader().setVisible(False)
        items.setEditTriggers(QAbstractItemView.NoEditTriggers)
        items.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        rows = data.get("items", [])
        items.setRowCount(len(rows))
        for r, it in enumerate(rows):
            cells = [it["product_name"], str(it["qty"]),
                     self.controller.fmt(it["line_total_minor"])]
            for c, val in enumerate(cells):
                cell = QTableWidgetItem(val)
                if c in (1, 2):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                items.setItem(r, c, cell)
        root.addWidget(QLabel("Items (read-only):"))
        root.addWidget(items, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {"date": self.date.date().toString("yyyy-MM-dd"),
                "notes": self.notes.text().strip()}
