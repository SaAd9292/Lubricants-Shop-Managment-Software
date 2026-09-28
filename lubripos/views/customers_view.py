"""Customers page: directory of customers with per-customer purchase history
("which oil did they buy last time?"). Searchable, sortable, paginated.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.customer_controller import CustomerController
from ..reports.report_exporter import to_pdf, to_xlsx
from ..services.column_presets import ColumnPresetStore
from ..ui.widgets import DataTable, number_rows
from .column_select_dialog import ColumnSelectDialog

PAGE_SIZE = 25
# label, sort key, right-aligned?
COLUMNS = [("Name", "name", False), ("Phone", None, False),
           ("Address", None, False),
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
        self._debounce.timeout.connect(self._reset_and_reload)  # search resets to page 1
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
        excel_btn = QPushButton("Export Excel")
        excel_btn.setObjectName("Secondary")
        excel_btn.clicked.connect(lambda: self._export("xlsx"))
        print_btn = QPushButton("Print")
        print_btn.setObjectName("Secondary")
        print_btn.clicked.connect(lambda: self._export("pdf"))
        header.addWidget(excel_btn)
        header.addWidget(print_btn)
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
        self.table.placeholder = ('No customers yet\n'
                                   "They're added automatically when you attach one "
                                   'to a sale, or click "+ Add Customer".')
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._on_sort)
        self.table.doubleClicked.connect(lambda: self._open_history())
        root.addWidget(self.table, 1)

        hint_row = QHBoxLayout()
        hint = QLabel("Double-click a customer to see their purchase history.")
        hint.setObjectName("Muted")
        hint_row.addWidget(hint)
        hint_row.addStretch(1)
        # live grand totals across the whole filtered set (no need to print)
        self.totals_lbl = QLabel("")
        self.totals_lbl.setStyleSheet("font-weight:600;")
        self.totals_lbl.setTextFormat(Qt.RichText)
        hint_row.addWidget(self.totals_lbl)
        root.addLayout(hint_row)

        footer = QHBoxLayout()
        hist_btn = QPushButton("Purchase history")
        hist_btn.setObjectName("Secondary")
        hist_btn.clicked.connect(self._open_history)
        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("Secondary")
        edit_btn.clicked.connect(self._edit_selected)
        self.del_btn = QPushButton("Remove")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.clicked.connect(self._delete_selected)
        debt_btn = QPushButton("Ledger")
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
        self._update_totals()

    def _update_totals(self) -> None:
        t = self.controller.list_totals(
            search=self.search.text(), only_active=not self.f_inactive.isChecked())
        fmt = self.controller.fmt
        recv = int(t.get("receivable", 0) or 0)
        credit = int(t.get("credit", 0) or 0)
        parts = [f"Owed by customers: <b>{fmt(recv)}</b>"]
        if credit:
            parts.append(f"Credit (shop owes): <b>{fmt(credit)}</b>")
            parts.append(f"Net: <b>{fmt(recv - credit)}</b>")
        parts.append(f"Lifetime spend: <b>{fmt(int(t.get('total_spent', 0) or 0))}</b>")
        self.totals_lbl.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        number_rows(self.table, self._page * PAGE_SIZE + 1)
        for r, c in enumerate(rows):
            name = QTableWidgetItem(c["name"] + ("" if c["is_active"] else "  (inactive)"))
            name.setData(Qt.UserRole, c["id"])
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(c.get("phone") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(c.get("address") or ""))
            n = _money_item(str(c.get("sales_count", 0)))
            self.table.setItem(r, 3, n)
            last = (c.get("last_purchase") or "")[:16]
            self.table.setItem(r, 4, QTableWidgetItem(last or "—"))
            self.table.setItem(r, 5, _money_item(self.controller.fmt(c.get("total_spent", 0))))
            bal = int(c.get("balance_owed", 0) or 0)
            if bal > 0:                                   # customer owes the shop
                bcell = _money_item(self.controller.fmt(bal))
                bcell.setForeground(QColor("#dc2626"))    # red
            elif bal < 0:                                 # the SHOP owes the customer
                bcell = _money_item(self.controller.fmt(-bal) + " (credit)")
                bcell.setForeground(QColor("#16a34a"))    # green
            else:
                bcell = _money_item("—")
            self.table.setItem(r, 6, bcell)

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

    def _export(self, fmt: str) -> None:
        """Export/print the WHOLE customer list (respecting the current search +
        active/inactive filter), not just the page on screen."""
        res = self.controller.list(
            search=self.search.text(),
            only_active=not self.f_inactive.isChecked(),
            limit=1_000_000, offset=0)
        customers = res["rows"]
        if not customers:
            QMessageBox.information(self, "Nothing to export",
                                    "No customers match the current filters.")
            return
        columns = [
            {"key": "num", "label": "#", "align": "right"},
            {"key": "name", "label": "Name"},
            {"key": "phone", "label": "Phone"},
            {"key": "address", "label": "Address"},
            {"key": "sales_count", "label": "Sales", "align": "right"},
            {"key": "last_purchase", "label": "Last purchase"},
            {"key": "total_spent", "label": "Total spent", "align": "right", "money": True},
            {"key": "balance_owed", "label": "Balance owed", "align": "right", "money": True},
        ]
        rows = [{
            "num": i + 1,
            "name": c["name"],
            "phone": c.get("phone") or "",
            "address": c.get("address") or "",
            "sales_count": c.get("sales_count") or 0,
            "last_purchase": (c.get("last_purchase") or "")[:10],
            "total_spent": c.get("total_spent") or 0,
            "balance_owed": c.get("balance_owed") or 0,
        } for i, c in enumerate(customers)]
        # let the user tick exactly which columns to print/export (with presets)
        result = ColumnSelectDialog.pick(
            self, columns, "customers", ColumnPresetStore(self.ctx.config.data_root))
        if result is None:
            return   # cancelled
        chosen, orientation = result
        columns = [c for c in columns if c["key"] in chosen]

        # grand totals across the WHOLE exported set (not just the visible page)
        total_spent = sum(int(c.get("total_spent") or 0) for c in customers)
        balances = [int(c.get("balance_owed") or 0) for c in customers]
        receivable = sum(b for b in balances if b > 0)   # customers owe the shop
        credit = -sum(b for b in balances if b < 0)      # shop owes customers (>=0)
        summary = [
            {"label": "Customers", "value": len(customers), "money": False},
            {"label": "Total spent (lifetime)", "value": total_spent, "money": True},
            {"label": "Total balance owed by customers", "value": receivable, "money": True},
        ]
        if credit:
            summary.append({"label": "Total credit (shop owes)", "value": credit, "money": True})
            summary.append({"label": "Net balance owed", "value": receivable - credit,
                            "money": True})

        company = self.ctx.company.get_company()
        scope = "Inactive" if self.f_inactive.isChecked() else "Active"
        report = {"key": "customers", "title": "Customer List",
                  "subtitle": f"{scope} · {len(customers)} customer(s)",
                  "columns": columns, "rows": rows, "orientation": orientation,
                  "summary": summary}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            if fmt == "xlsx":
                suggested = str(Path.home() / f"customers_{stamp}.xlsx")
                chosen, _ = QFileDialog.getSaveFileName(
                    self, "Save customers as", suggested, "Excel files (*.xlsx)")
                if not chosen:
                    return
                path = to_xlsx(report, company, chosen)
                QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            else:  # pdf -> open for printing
                path = to_pdf(report, company, os.path.join(
                    tempfile.gettempdir(), f"customers_{stamp}.pdf"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

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
        self.phone.setPlaceholderText("optional")
        self.address = QLineEdit()
        self.address.setPlaceholderText("optional")
        self.notes = QLineEdit()
        # opening balance: money the customer already owed on paper before going
        # digital. Adds straight into their "balance owed".
        self.opening = QDoubleSpinBox()
        self.opening.setRange(-99_999_999, 99_999_999)   # negative = the SHOP owes them
        self.opening.setDecimals(2)
        self.opening.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.opening.setToolTip(
            "Balance carried over from your paper records. Positive = the customer "
            "owes you; negative = you owe the customer (advance / credit). "
            "Leave 0 for a brand-new customer.")
        form.addRow("Name *", self.name)
        form.addRow("Phone", self.phone)
        form.addRow("Address", self.address)
        form.addRow("Opening balance owed", self.opening)
        form.addRow("Notes", self.notes)
        _, self._mu = controller.currency()
        if customer_id is not None:
            c = controller.get(customer_id)
            self.name.setText(c.get("name") or "")
            self.phone.setText(c.get("phone") or "")
            self.address.setText(c.get("address") or "")
            self.notes.setText(c.get("notes") or "")
            self.opening.setValue((c.get("opening_debt_minor") or 0) / self._mu)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setObjectName("Success")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _save(self) -> None:
        form = {"name": self.name.text().strip(), "phone": self.phone.text().strip(),
                "address": self.address.text().strip(),
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
    """Read-only MONEY ledger for one customer, in classic Debit / Credit form.

    Debit  = amount charged to the customer (credit/udhaar sales + any opening
             balance) — increases what they owe.
    Credit = amount received from the customer (recoveries/payments) —
             decreases what they owe.
    Balance = the running amount owed after each entry.

    This is purely the money view; a customer's PURCHASE history (what products
    they bought) is a separate screen. Recording a recovery lives on the Cash
    Recovery sidebar screen."""

    def __init__(self, parent, controller: CustomerController, customer_id: int) -> None:
        super().__init__(parent)
        self.controller = controller
        self.customer_id = customer_id
        self.setWindowTitle("Customer ledger")
        self.resize(720, 520)
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

        root.addWidget(QLabel("Ledger — debit (charged) and credit (paid)"))
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(
            ["Date", "Details", "Debit", "Credit", "Balance"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.tbl, 1)

        # totals strip under the table
        self.totals_lbl = QLabel("")
        self.totals_lbl.setObjectName("Muted")
        root.addWidget(self.totals_lbl)

        hint = QLabel("To record a payment, use the Cash Recovery screen in the "
                      "sidebar.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bar = QHBoxLayout()
        print_btn = QPushButton("Print / PDF")
        print_btn.setObjectName("Secondary")
        print_btn.clicked.connect(lambda: self._export("pdf"))
        excel_btn = QPushButton("Export Excel")
        excel_btn.setObjectName("Secondary")
        excel_btn.clicked.connect(lambda: self._export("xlsx"))
        bar.addWidget(print_btn)
        bar.addWidget(excel_btn)
        bar.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("Secondary")
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        root.addLayout(bar)

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

        entries = self._ledger_entries(data)
        self.tbl.setRowCount(len(entries))
        running = 0
        for r, (dt, details, debit, credit) in enumerate(entries):
            running += debit - credit
            self.tbl.setItem(r, 0, QTableWidgetItem(dt))
            self.tbl.setItem(r, 1, QTableWidgetItem(details))
            dcell = _money_item(fmt(debit) if debit else "")
            if debit:
                dcell.setForeground(QColor("#dc2626"))
            self.tbl.setItem(r, 2, dcell)
            ccell = _money_item(fmt(credit) if credit else "")
            if credit:
                ccell.setForeground(QColor("#16a34a"))
            self.tbl.setItem(r, 3, ccell)
            bcell = _money_item(fmt(running))
            bcell.setForeground(QColor("#dc2626" if running > 0 else "#16a34a"))
            self.tbl.setItem(r, 4, bcell)

        self.totals_lbl.setText(
            f"Total debit (charged):  {fmt(data.get('charged_total', 0))}"
            f"      Total credit (paid):  {fmt(data.get('paid_total', 0))}"
            f"      Balance owed:  {fmt(bal)}")

    @staticmethod
    def _ledger_entries(data: dict) -> list[tuple]:
        """One date-ordered list of (date, details, debit_minor, credit_minor):
        charges are debits (owe more), payments are credits (owe less)."""
        entries = []
        for c in data["charges"]:
            ref = c.get("ref") or ""
            details = ref if ref.startswith("Opening") else f"Purchase — Invoice {ref}"
            entries.append((c["date"], details, int(c["amount"]), 0))
        for p in data["payments"]:
            detail = p.get("method") or "Payment"
            if p.get("notes"):
                detail = (detail + " — " + p["notes"]).strip(" —")
            entries.append((p["date"], detail, 0, int(p["amount"])))
        entries.sort(key=lambda e: e[0])
        return entries

    # -- print / export ----------------------------------------------
    def _report(self) -> dict:
        """Build a generic report dict (printable PDF / Excel) for this
        customer's ledger. Debit/Credit/Balance are pre-formatted strings so the
        zero side of each row prints blank rather than 'Rs 0.00'."""
        data = self.controller.ledger(self.customer_id)
        cust = data["customer"]
        fmt = self.controller.fmt
        rows, running = [], 0
        for dt, details, debit, credit in self._ledger_entries(data):
            running += debit - credit
            rows.append({
                "date": dt, "details": details,
                "debit": fmt(debit) if debit else "",
                "credit": fmt(credit) if credit else "",
                "balance": fmt(running),
            })
        columns = [
            {"key": "date", "label": "Date"},
            {"key": "details", "label": "Details"},
            {"key": "debit", "label": "Debit", "align": "right"},
            {"key": "credit", "label": "Credit", "align": "right"},
            {"key": "balance", "label": "Balance", "align": "right"},
        ]
        sub = cust["name"] + (f"  ·  {cust['phone']}" if cust.get("phone") else "")
        return {
            "key": "customer_ledger", "title": "Customer Ledger",
            "subtitle": sub, "columns": columns, "rows": rows,
            "orientation": "portrait",
            "summary": [
                {"label": "Total debit (charged)", "value": data.get("charged_total", 0),
                 "money": True},
                {"label": "Total credit (paid)", "value": data.get("paid_total", 0),
                 "money": True},
                {"label": "Balance owed", "value": data.get("balance", 0), "money": True},
            ],
        }

    def _export(self, fmt: str) -> None:
        company = self.controller.ctx.company.get_company()
        report = self._report()
        cust = report["subtitle"].split("  ·  ")[0].replace(" ", "_")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            if fmt == "xlsx":
                suggested = str(Path.home() / f"ledger_{cust}_{stamp}.xlsx")
                chosen, _ = QFileDialog.getSaveFileName(
                    self, "Save ledger as", suggested, "Excel files (*.xlsx)")
                if not chosen:
                    return
                path = to_xlsx(report, company, chosen)
                QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            else:   # pdf -> open for printing
                path = to_pdf(report, company, os.path.join(
                    tempfile.gettempdir(), f"ledger_{cust}_{stamp}.pdf"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
