"""All payments made to suppliers — a printable list.

Opened from the Payables page. Shows every supplier payment (date, supplier,
amount, method, account, note) over a date range (defaulting to all of them),
with Print/PDF and Excel export.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.payable_controller import PayableController
from ..core.session import current_session
from ..reports.report_exporter import to_pdf, to_xlsx

_COLS = ["Date", "Supplier", "Amount", "Method", "Note"]
_METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]


class SupplierPaymentsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.controller = PayableController(ctx)
        self._rows: list[dict] = []
        self.setWindowTitle("Supplier payments")
        self.resize(820, 600)
        self._build()
        self._reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("From:"))
        self.d_from = QDateEdit()
        self.d_from.setCalendarPopup(True)
        self.d_from.setDisplayFormat("dd MMM yyyy")
        self.d_from.setMaximumDate(QDate.currentDate())
        min_d = self.controller.payments_min_date()
        self.d_from.setDate(QDate.fromString(min_d, "yyyy-MM-dd")
                            if min_d else QDate.currentDate())
        self.d_from.dateChanged.connect(self._reload)
        bar.addWidget(self.d_from)
        bar.addWidget(QLabel("To:"))
        self.d_to = QDateEdit()
        self.d_to.setCalendarPopup(True)
        self.d_to.setDisplayFormat("dd MMM yyyy")
        self.d_to.setMaximumDate(QDate.currentDate())
        self.d_to.setDate(QDate.currentDate())
        self.d_to.dateChanged.connect(self._reload)
        bar.addWidget(self.d_to)
        bar.addStretch(1)
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700;")
        bar.addWidget(self.total_lbl)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._sync_btns)
        root.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self._is_admin = bool(current_session.user
                              and current_session.user.role == "admin")
        self.edit_btn = QPushButton("Edit selected")
        self.edit_btn.setObjectName("Secondary")
        self.edit_btn.setToolTip("Correct this payment — supplier, amount, "
                                 "method, date or note (admin)")
        self.edit_btn.clicked.connect(self._edit)
        self.edit_btn.setEnabled(False)
        self.reverse_btn = QPushButton("Reverse selected")
        self.reverse_btn.setObjectName("Secondary")
        self.reverse_btn.setToolTip("Undo this payment: the supplier's balance "
                                    "and cash both self-correct (admin)")
        self.reverse_btn.clicked.connect(self._reverse)
        self.reverse_btn.setEnabled(False)
        if self._is_admin:
            foot.addWidget(self.edit_btn)
            foot.addWidget(self.reverse_btn)
        self.print_btn = QPushButton("Print / PDF")
        self.print_btn.setObjectName("Secondary")
        self.print_btn.clicked.connect(lambda: self._export("pdf"))
        self.excel_btn = QPushButton("Export Excel")
        self.excel_btn.setObjectName("Secondary")
        self.excel_btn.clicked.connect(lambda: self._export("xlsx"))
        foot.addWidget(self.print_btn)
        foot.addWidget(self.excel_btn)
        foot.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        root.addLayout(foot)

    def _reload(self) -> None:
        d_from = self.d_from.date().toString("yyyy-MM-dd")
        d_to = self.d_to.date().toString("yyyy-MM-dd")
        data = self.controller.payments(date_from=d_from, date_to=d_to)
        self._rows = data["rows"]
        fmt = self.controller.fmt
        self.table.setRowCount(len(self._rows))
        for r, p in enumerate(self._rows):
            cells = [p["date"], p["supplier"], fmt(p["amount"]),
                     p["method"], p.get("notes") or ""]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, p.get("id"))
                if c == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.total_lbl.setText(f"{len(self._rows)} payment(s)  ·  total {fmt(data['total'])}")
        self._sync_btns()

    def _sync_btns(self) -> None:
        on = self._is_admin and self.table.currentRow() >= 0
        self.edit_btn.setEnabled(on)
        self.reverse_btn.setEnabled(on)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def _reverse(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        row = self.table.currentRow()
        who = self.table.item(row, 1).text()
        amt = self.table.item(row, 2).text()
        confirm = QMessageBox.warning(
            self, "Reverse payment",
            f"Reverse this payment of {amt} to {who}?\n\n"
            "The amount goes back onto what you owe the supplier, and cash "
            "self-corrects. This cannot itself be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.reverse_payment(pid)
        if ok:
            QMessageBox.information(self, "Reversed", "The payment was reversed.")
            self._reload()
        else:
            QMessageBox.warning(self, "Could not reverse", msg)

    def _edit(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        try:
            detail = self.controller.get_supplier_payment(pid)
        except Exception as exc:
            QMessageBox.warning(self, "Could not open", str(exc))
            return
        dlg = SupplierPaymentEditDialog(self.controller, detail, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        ok, msg, _ = self.controller.edit_payment(
            pid, supplier_id=v["supplier_id"], amount=v["amount"], method=v["method"],
            payment_date=v["date"], notes=v["notes"])
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not save", msg)

    def _report(self) -> dict:
        rows = [{"date": p["date"], "supplier": p["supplier"],
                 "amount": p["amount"], "method": p["method"],
                 "notes": p.get("notes") or ""}
                for p in self._rows]
        total = sum(p["amount"] for p in self._rows)
        return {
            "key": "supplier_payments", "title": "Supplier Payments",
            "subtitle": f"{self.d_from.date().toString('yyyy-MM-dd')} to "
                        f"{self.d_to.date().toString('yyyy-MM-dd')}",
            "orientation": "portrait",
            "columns": [
                {"key": "date", "label": "Date"},
                {"key": "supplier", "label": "Supplier"},
                {"key": "amount", "label": "Amount", "align": "right", "money": True},
                {"key": "method", "label": "Method"},
                {"key": "notes", "label": "Note"},
            ],
            "rows": rows,
            "summary": [
                {"label": "Payments", "value": len(rows), "money": False},
                {"label": "Total paid to suppliers", "value": total, "money": True}],
        }

    def _export(self, fmt: str) -> None:
        company = self.ctx.company.get_company()
        report = self._report()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            if fmt == "xlsx":
                from PySide6.QtWidgets import QFileDialog
                suggested = str(Path.home() / f"supplier_payments_{stamp}.xlsx")
                chosen, _ = QFileDialog.getSaveFileName(
                    self, "Save payments as", suggested, "Excel files (*.xlsx)")
                if not chosen:
                    return
                path = to_xlsx(report, company, chosen)
                QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            else:
                path = to_pdf(report, company, os.path.join(
                    tempfile.gettempdir(), f"supplier_payments_{stamp}.pdf"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))


class SupplierPaymentEditDialog(QDialog):
    """Correct a supplier payment: supplier, amount, method, date, note."""

    def __init__(self, controller: PayableController, detail: dict,
                 parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Edit supplier payment")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.supplier = QComboBox()
        try:
            rows = controller.list(only_outstanding=False)["rows"]
        except Exception:
            rows = []
        want = detail.get("supplier_id")
        sel = 0
        for i, s in enumerate(rows):
            self.supplier.addItem(s["name"], s["id"])
            if s["id"] == want:
                sel = i
        if not rows:   # fall back so the current supplier is at least shown
            self.supplier.addItem(detail.get("supplier_name") or "(supplier)", want)
        self.supplier.setCurrentIndex(sel)
        form.addRow("Supplier", self.supplier)

        sym, self._mu = controller.currency()
        self.amount = QDoubleSpinBox()
        self.amount.setMaximum(1_000_000_000)
        self.amount.setDecimals(2)
        self.amount.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.amount.setPrefix(f"{sym} ")
        self.amount.setValue((detail.get("amount_minor") or 0) / (self._mu or 100))
        form.addRow("Amount", self.amount)

        self.method = QComboBox()
        self.method.addItems(_METHODS)
        mi = self.method.findText(detail.get("method") or "Cash")
        self.method.setCurrentIndex(mi if mi >= 0 else 0)
        form.addRow("Method", self.method)

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        full = (detail.get("payment_date") or "")[:10]
        qd = QDate.fromString(full, "yyyy-MM-dd")
        self.date.setDate(qd if qd.isValid() else QDate.currentDate())
        form.addRow("Date", self.date)

        self.note = QLineEdit(detail.get("notes") or "")
        form.addRow("Note", self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        if self.supplier.currentData() is None:
            QMessageBox.information(self, "Pick a supplier", "Choose a supplier.")
            return
        if self.amount.value() <= 0:
            QMessageBox.information(self, "Enter amount",
                                    "Amount must be greater than zero.")
            return
        self.accept()

    def values(self) -> dict:
        return {"supplier_id": self.supplier.currentData(),
                "amount": self.amount.value(),
                "method": self.method.currentText(),
                "date": self.date.date().toString("yyyy-MM-dd"),
                "notes": self.note.text().strip()}
