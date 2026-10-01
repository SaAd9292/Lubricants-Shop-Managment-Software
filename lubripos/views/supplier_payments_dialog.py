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
    QAbstractItemView, QDateEdit, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.payable_controller import PayableController
from ..reports.report_exporter import to_pdf, to_xlsx

_COLS = ["Date", "Supplier", "Amount", "Method", "Note"]


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
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        foot = QHBoxLayout()
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
                if c == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.total_lbl.setText(f"{len(self._rows)} payment(s)  ·  total {fmt(data['total'])}")

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
