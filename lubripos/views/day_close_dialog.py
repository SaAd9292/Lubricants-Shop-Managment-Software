"""Daily Sales Report (Day Close) in a pop-up window.

Opened from the dashboard. Defaults to today; pick any past day and it rebuilds.
Print/PDF and Excel reuse the shared report exporter.
"""
from __future__ import annotations

from PySide6.QtCore import QDate, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.report_controller import ReportController
from ..core import money
from .day_close_widget import DayCloseWidget


class DayCloseDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.controller = ReportController(ctx)
        self._report: dict | None = None
        self.setWindowTitle("Day Close — Daily Sales Report")
        self.resize(1000, 720)
        self._build()
        self._reload()

    def _fmt(self, minor: int) -> str:
        c = self.ctx.company.get_company()
        return money.format_money(int(minor or 0), c.get("currency_symbol", "Rs"),
                                  c.get("currency_minor_units", 100))

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Day:"))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        self.date.setDate(QDate.currentDate())
        self.date.dateChanged.connect(self._reload)
        bar.addWidget(self.date)
        bar.addStretch(1)
        self.print_btn = QPushButton("Print / PDF")
        self.print_btn.setObjectName("Secondary")
        self.print_btn.clicked.connect(lambda: self._export("pdf"))
        self.excel_btn = QPushButton("Export Excel")
        self.excel_btn.setObjectName("Secondary")
        self.excel_btn.clicked.connect(lambda: self._export("xlsx"))
        bar.addWidget(self.print_btn)
        bar.addWidget(self.excel_btn)
        root.addLayout(bar)

        self.widget = DayCloseWidget()      # own scroll; it's the whole window body
        root.addWidget(self.widget, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        root.addLayout(foot)

    def _day(self) -> str:
        return self.date.date().toString("yyyy-MM-dd")

    def _reload(self) -> None:
        try:
            self._report = self.controller.build("daily_sales", self._day(), self._day())
            self.widget.render(self._report, self._fmt)
        except Exception as exc:
            QMessageBox.warning(self, "Could not build report", str(exc))

    def _export(self, fmt: str) -> None:
        if not self._report:
            return
        ok, msg, path = self.controller.export(self._report, fmt)
        if not ok:
            QMessageBox.warning(self, "Export failed", msg)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
