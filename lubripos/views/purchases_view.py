"""Purchases page: purchase history + create new purchase + view details."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.session import current_session
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

    def _view_details(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        data = self.controller.get(pid)
        PurchaseDetailDialog(data, self.controller.fmt).exec()

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
    def __init__(self, purchase: dict, fmt_fn) -> None:
        super().__init__()
        self._fmt = fmt_fn
        self.setWindowTitle(f"Purchase #{purchase['id']}")
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

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        root.addWidget(close)


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
