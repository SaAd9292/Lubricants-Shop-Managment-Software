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
    QScrollArea, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..ui.widgets import DataTable, FlowLayout

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
        # Everything lives inside a scroll area so a short window scrolls instead
        # of squashing the stacked tables until their contents overlap.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # cards WRAP to the next line on a narrow window (no clipping)
        self.kpi_row = FlowLayout(spacing=12)
        root.addLayout(self.kpi_row)
        self.pay_row = FlowLayout(spacing=12)
        root.addLayout(self.pay_row)

        # Section panels are built DYNAMICALLY in render() from whatever the
        # report provides, so renaming or adding a section never blanks a panel.
        body = QHBoxLayout()
        body.setSpacing(16)
        self._left = QVBoxLayout()
        self._right = QVBoxLayout()
        body.addLayout(self._left, 2)
        body.addLayout(self._right, 1)
        root.addLayout(body, 1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _h(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:700; font-size:14px; color:#1f1f1f;")
        return lbl

    def _total_label(self) -> QLabel:
        lbl = QLabel("")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl.setStyleSheet("font-weight:700; font-size:13px; color:#1f1f1f;")
        return lbl

    def _table(self, placeholder: str, min_height: int = 130) -> DataTable:
        t = DataTable(0, 0)
        t.placeholder = placeholder
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setMinimumHeight(min_height)   # never squash below this (no overlap)
        return t

    # -- public render ------------------------------------------------
    def render(self, report: dict[str, Any], fmt: Callable[[int], str]) -> None:
        self._fmt = fmt
        summ = {s["label"]: s["value"] for s in report.get("summary", [])}

        net_today = summ.get("Today's cash (net)", 0)
        self._fill_cards(self.kpi_row, [
            ("Gross sales", fmt(summ.get("Gross sales", 0)), _ACCENT),
            ("Money received", fmt(summ.get("Money received", 0)), _GREEN),
            ("Opening cash", fmt(summ.get("Opening cash", 0)), _MUTED),
            ("Today's cash (in − out)", fmt(net_today),
             _GREEN if net_today >= 0 else _RED),
            ("Cash in hand", fmt(summ.get("Cash in hand", 0)),
             "#0f172a" if summ.get("Cash in hand", 0) >= 0 else _RED),
            ("Refunds", fmt(summ.get("Refunds", 0)), _RED),
            ("Expenses", fmt(summ.get("Expenses", 0)), _RED),
            ("Invoices", str(summ.get("Invoices", 0)), _MUTED),
        ])

        pays = report.get("payments", {})
        self._fill_cards(self.pay_row,
                         [(m, fmt(pays.get(m, 0)), None) for m in _METHODS])

        # Render EVERY section the report provides. Sales-type sections take the
        # wide left column; everything else stacks on the right. This never
        # breaks when a section is renamed or added.
        self._clear_layout(self._left)
        self._clear_layout(self._right)
        left_secs, right_secs = [], []
        for sec in report.get("sections", []):
            if sec.get("name", "").startswith(("Cash & paid", "Udhaar")):
                left_secs.append(sec)
            else:
                right_secs.append(sec)
        # the Cash drawer (cash in − out → closing) is what the owner checks most,
        # so render it FIRST in the right column instead of at the very bottom.
        right_secs.sort(key=lambda s: 0 if s.get("name", "").startswith("Cash drawer")
                        else 1)
        for sec in left_secs:
            self._add_section(self._left, sec)
        for sec in right_secs:
            self._add_section(self._right, sec)
        self._left.addStretch(1)
        self._right.addStretch(1)

    def _add_section(self, layout, sec: dict) -> None:
        layout.addWidget(self._h(sec.get("name", "")))
        tbl = self._table("Nothing to show.", 120)
        self._fill_table(tbl, sec)
        layout.addWidget(tbl)
        if sec.get("total_label") is not None:
            tl = self._total_label()
            tl.setText(f"{sec['total_label']}:  {self._fmt(sec.get('total', 0))}")
            layout.addWidget(tl)

    # -- helpers ------------------------------------------------------
    def _fill_cards(self, layout, items) -> None:
        self._clear_layout(layout)
        for title, value, color in items:
            layout.addWidget(self._card(title, value, color))

    def _card(self, title: str, value: str, color: str | None) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumWidth(150)
        card.setMinimumHeight(62)
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
