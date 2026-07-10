"""Stacked multi-section report renderer (layout='sections').

Renders a report that carries a list of ``sections`` (each with its own
columns/rows/total) as vertically stacked labelled tables inside a scroll
area, followed by the overall summary line. Used by reports that need more
than one grid but not the day-close card layout (e.g. Monthly Sales:
'By day' + 'By product').
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QScrollArea,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..ui.widgets import DataTable

_ROW_H = 28  # approx row height used to size each table to its content


class SectionsWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._fmt: Callable[[int], str] = str
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.vbox = QVBoxLayout(self.inner)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(8)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll)

    # -- public render ------------------------------------------------
    def render(self, report: dict[str, Any], fmt: Callable[[int], str]) -> None:
        self._fmt = fmt
        self._clear()
        for sec in report.get("sections", []):
            self.vbox.addWidget(self._heading(sec["name"]))
            self.vbox.addWidget(self._table(sec))
            self.vbox.addWidget(self._total(sec))
        summ = report.get("summary", [])
        if summ:
            self.vbox.addWidget(self._heading("Summary"))
            self.vbox.addWidget(self._summary_label(summ))
        self.vbox.addStretch(1)

    # -- builders -----------------------------------------------------
    def _heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:700; font-size:14px; color:#1f1f1f; margin-top:4px;")
        return lbl

    def _total(self, sec: dict) -> QLabel:
        lbl = QLabel(f"{sec['total_label']}:  {self._fmt(sec['total'])}")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl.setStyleSheet("font-weight:700; font-size:13px; color:#1f1f1f;")
        return lbl

    def _summary_label(self, summary: list[dict]) -> QLabel:
        parts = []
        for s in summary:
            v = self._fmt(s["value"]) if s.get("money") else str(s["value"])
            parts.append(f"{s['label']}: {v}")
        lbl = QLabel("     ".join(parts))
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-weight:600;")
        return lbl

    def _table(self, sec: dict) -> DataTable:
        cols = sec["columns"]
        rows = sec["rows"]
        t = DataTable(0, 0)
        t.placeholder = "No data for this period."
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setColumnCount(len(cols))
        t.setHorizontalHeaderLabels([c["label"] for c in cols])
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                val = row.get(col["key"])
                text = self._fmt(val) if col.get("money") else (
                    "" if val is None else str(val))
                item = QTableWidgetItem(text)
                if col.get("align") == "right":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, item)
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)
        # size each table to its content; the outer scroll area handles overflow
        t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        t.setFixedHeight((max(1, len(rows)) + 1) * _ROW_H + 6)
        return t

    def _clear(self) -> None:
        while self.vbox.count():
            item = self.vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
