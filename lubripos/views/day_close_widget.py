"""Day-close (Daily Sales Report) grid renderer.

Renders the multi-section ``layout='day_close'`` report as a professional
grid instead of a single flat table:

  * KPI cards       - Gross sales, Expenses, Net, Invoices
  * payment cards   - Cash / Bank / EasyPaisa / JazzCash amounts received
  * two grids       - "Sales" (left, one row per sale line) and, in the
                      "Expenses" and "Money received"

It is a pure view: it takes the report dict built by ReportService.daily_sales
plus a money-formatting callable, and paints itself. Safe to call repeatedly.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..ui.widgets import DataTable

# payment channels always shown (even at zero) so the owner can eyeball the
# cash-vs-digital split at a glance
_METHODS = ["Cash", "Bank", "EasyPaisa", "JazzCash"]

_ACCENT = "#2563eb"
_RED = "#b91c1c"
_GREEN = "#16a34a"
_MUTED = "#6b7280"


class DayCloseWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._fmt: Callable[[int], str] = str
        self._build()

    # -- construction -------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(12)
        root.addLayout(self.kpi_row)

        self.pay_row = QHBoxLayout()
        self.pay_row.setSpacing(12)
        root.addLayout(self.pay_row)

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.addWidget(self._h("Sales"))
        self.sales_tbl = self._table("No sales recorded for this day.")
        left.addWidget(self.sales_tbl, 1)
        self.sales_total = self._total_label()
        left.addWidget(self.sales_total)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        right.addWidget(self._h("Expenses"))
        self.exp_tbl = self._table("No expenses recorded for this day.")
        right.addWidget(self.exp_tbl, 1)
        self.exp_total = self._total_label()
        right.addWidget(self.exp_total)
        right.addWidget(self._h("Money received"))
        self.pay_tbl = self._table("No payments recorded.")
        right.addWidget(self.pay_tbl, 1)
        right.addWidget(self._h("Returns"))
        self.returns_tbl = self._table("No returns for this day.")
        right.addWidget(self.returns_tbl, 1)
        self.returns_total = self._total_label()
        right.addWidget(self.returns_total)
        body.addLayout(right, 1)

        root.addLayout(body, 1)

    def _h(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:700; font-size:14px; color:#1f1f1f;")
        return lbl

    def _total_label(self) -> QLabel:
        lbl = QLabel("")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl.setStyleSheet("font-weight:700; font-size:13px; color:#1f1f1f;")
        return lbl

    def _table(self, placeholder: str) -> DataTable:
        t = DataTable(0, 0)
        t.placeholder = placeholder
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        return t

    # -- public render ------------------------------------------------
    def render(self, report: dict[str, Any], fmt: Callable[[int], str]) -> None:
        self._fmt = fmt
        summ = {s["label"]: s["value"] for s in report.get("summary", [])}

        self._fill_cards(self.kpi_row, [
            ("Gross sales", fmt(summ.get("Gross sales", 0)), _ACCENT),
            ("Refunds", fmt(summ.get("Refunds", 0)), _RED),
            ("Expenses", fmt(summ.get("Expenses", 0)), _RED),
            ("Net", fmt(summ.get("Net", 0)), _GREEN),
            ("Invoices", str(summ.get("Invoices", 0)), _MUTED),
        ])

        pays = report.get("payments", {})
        self._fill_cards(self.pay_row,
                         [(m, fmt(pays.get(m, 0)), None) for m in _METHODS])

        secs = {s["name"]: s for s in report.get("sections", [])}
        for name, table, total in (
            ("Sales", self.sales_tbl, self.sales_total),
            ("Expenses", self.exp_tbl, self.exp_total),
            ("Returns", self.returns_tbl, self.returns_total),
        ):
            sec = secs.get(name)
            if sec:
                self._fill_table(table, sec)
                total.setText(f"{sec['total_label']}:  {fmt(sec['total'])}")
        if secs.get("Money received"):
            self._fill_table(self.pay_tbl, secs["Money received"])

    # -- helpers ------------------------------------------------------
    def _fill_cards(self, layout: QHBoxLayout, items) -> None:
        self._clear_layout(layout)
        for title, value, color in items:
            layout.addWidget(self._card(title, value, color))
        layout.addStretch(1)

    def _card(self, title: str, value: str, color: str | None) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumWidth(150)
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-size:11px; font-weight:600; color:{_MUTED};")
        val = QLabel(value)
        style = "font-size:19px; font-weight:700;"
        if color:
            style += f" color:{color};"
        val.setStyleSheet(style)
        v.addWidget(t)
        v.addWidget(val)
        return card

    def _fill_table(self, table: DataTable, section: dict) -> None:
        cols = section["columns"]
        rows = section["rows"]
        table.clear()
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels([c["label"] for c in cols])
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                val = row.get(col["key"])
                text = self._fmt(val) if col.get("money") else (
                    "" if val is None else str(val))
                item = QTableWidgetItem(text)
                if col.get("align") == "right":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, item)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
