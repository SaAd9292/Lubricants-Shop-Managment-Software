"""Reports page: choose a report, set date range/filters, preview, export."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.report_controller import ReportController
from .day_close_widget import DayCloseWidget
from .report_sections_widget import SectionsWidget

# (label, key, mode)  mode: day | month | range | none
REPORTS = [
    ("Daily Sales", "daily_sales", "day"),
    ("Monthly Sales", "monthly_sales", "month"),
    ("Profit", "profit", "range"),
    ("Stock", "stock", "none"),
    ("Low Stock", "low_stock", "none"),
    ("Purchases", "purchases", "range"),
    ("Expenses", "expenses", "range"),
    ("GST / Tax", "tax", "range"),
]


class ReportsView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = ReportController(ctx)
        self._report: dict | None = None
        self._build_ui()
        self._on_type_changed()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel("Reports")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        controls = QHBoxLayout()
        self.type = QComboBox()
        for label, key, mode in REPORTS:
            self.type.addItem(label, (key, mode))
        self.type.currentIndexChanged.connect(self._on_type_changed)
        controls.addWidget(QLabel("Report:"))
        controls.addWidget(self.type)

        self.lbl_from = QLabel("From:")
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.lbl_to = QLabel("To:")
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setDate(QDate.currentDate())
        controls.addWidget(self.lbl_from)
        controls.addWidget(self.date_from)
        controls.addWidget(self.lbl_to)
        controls.addWidget(self.date_to)

        # Stock-report-only filters
        self.lbl_brand = QLabel("Brand:")
        self.f_brand = QComboBox()
        self.f_brand.addItem("All brands", None)
        for b in self.controller.brands():
            self.f_brand.addItem(b["name"], b["id"])
        self.lbl_product = QLabel("Product:")
        self.f_product = QComboBox()
        self.f_product.addItem("All products", None)
        for p in self.controller.all_products():
            self.f_product.addItem(p["name"], p["id"])
        controls.addWidget(self.lbl_brand)
        controls.addWidget(self.f_brand)
        controls.addWidget(self.lbl_product)
        controls.addWidget(self.f_product)

        gen = QPushButton("Generate")
        gen.clicked.connect(self._generate)
        controls.addWidget(gen)
        controls.addStretch(1)
        root.addLayout(controls)

        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        root.addWidget(self.hint)

        self.table = DataTable(0, 0)
        self.table.placeholder = "Choose a report and date range, then click Generate."
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        # Daily Sales uses a multi-panel "day close" grid instead of the flat
        # table; only one of the two is visible at a time (see _render).
        self.dayclose = DayCloseWidget()
        self.dayclose.setVisible(False)
        root.addWidget(self.dayclose, 1)

        # Multi-section reports (e.g. Monthly Sales: by day + by product)
        self.sections = SectionsWidget()
        self.sections.setVisible(False)
        root.addWidget(self.sections, 1)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight:600;")
        root.addWidget(self.summary)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.pdf_btn = QPushButton("Export PDF")
        self.pdf_btn.clicked.connect(lambda: self._export("pdf"))
        self.xlsx_btn = QPushButton("Export Excel")
        self.xlsx_btn.setObjectName("Secondary")
        self.xlsx_btn.clicked.connect(lambda: self._export("xlsx"))
        self.print_btn = QPushButton("Print")
        self.print_btn.setObjectName("Secondary")
        self.print_btn.clicked.connect(self._print)
        for b in (self.pdf_btn, self.xlsx_btn, self.print_btn):
            b.setEnabled(False)
            actions.addWidget(b)
        root.addLayout(actions)

    def _mode(self) -> str:
        return self.type.currentData()[1]

    def _on_type_changed(self) -> None:
        mode = self._mode()
        key = self.type.currentData()[0]
        # Sensible default date per mode. Day/Month reports are about a single
        # point in time, so default to TODAY (the old code defaulted the shared
        # 'from' field to 30 days ago, which made Daily Sales look empty because
        # it queried a month back). Range reports keep a trailing-30-day window.
        if mode in ("day", "month"):
            self.date_from.setDate(QDate.currentDate())
        elif mode == "range":
            self.date_from.setDate(QDate.currentDate().addDays(-30))
            self.date_to.setDate(QDate.currentDate())
        show_to = mode == "range"
        show_from = mode in ("range", "day", "month")
        self.lbl_from.setVisible(show_from)
        self.date_from.setVisible(show_from)
        self.lbl_to.setVisible(show_to)
        self.date_to.setVisible(show_to)
        show_stock = key == "stock"
        for w in (self.lbl_brand, self.f_brand, self.lbl_product, self.f_product):
            w.setVisible(show_stock)
        hints = {
            "day": "Uses the 'From' date as the report day.",
            "month": "Uses the month/year of the 'From' date.",
            "range": "Uses the From-To date range (inclusive).",
            "none": "This report is a current snapshot; dates are ignored.",
        }
        self.lbl_from.setText("Month:" if mode == "month" else "Date:" if mode == "day" else "From:")
        self.hint.setText("Filter by brand and/or product (optional)." if show_stock
                          else hints.get(mode, ""))

    # -- generate -----------------------------------------------------
    def _generate(self) -> None:
        key = self.type.currentData()[0]
        d_from = self.date_from.date().toString("yyyy-MM-dd")
        d_to = self.date_to.date().toString("yyyy-MM-dd")
        if self._mode() == "range" and d_to < d_from:
            QMessageBox.warning(self, "Invalid range", "'To' date is before 'From' date.")
            return
        brand_id = self.f_brand.currentData() if key == "stock" else None
        product_id = self.f_product.currentData() if key == "stock" else None
        try:
            self._report = self.controller.build(key, d_from, d_to,
                                                 brand_id=brand_id, product_id=product_id)
        except Exception as exc:
            QMessageBox.warning(self, "Could not build report", str(exc))
            return
        self._render(self._report)
        for b in (self.pdf_btn, self.xlsx_btn, self.print_btn):
            b.setEnabled(True)

    def _show_only(self, widget) -> None:
        """Show one render surface (table / dayclose / sections) and hide the
        rest, including the flat-table summary label."""
        for w in (self.table, self.summary, self.dayclose, self.sections):
            w.setVisible(w is widget)

    def _render(self, report: dict) -> None:
        # Route by layout: day-close grid, stacked sections, or flat table.
        layout = report.get("layout")
        if layout == "day_close":
            self._show_only(self.dayclose)
            self.dayclose.render(report, self.controller.fmt)
            return
        if layout == "sections":
            self._show_only(self.sections)
            self.sections.render(report, self.controller.fmt)
            return
        self.table.setVisible(True)
        self.summary.setVisible(True)
        self.dayclose.setVisible(False)
        self.sections.setVisible(False)
        cols = report["columns"]
        rows = report["rows"]
        # empty-state text shown by DataTable when a report returns no rows
        self.table.placeholder = "" if rows else "No data for the selected range."
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([c["label"] for c in cols])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                val = row.get(col["key"])
                text = self.controller.fmt(val) if col.get("money") else (
                    "" if val is None else str(val))
                item = QTableWidgetItem(text)
                if col.get("align") == "right":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        if cols:
            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
            hdr.setStretchLastSection(True)

        parts = []
        for s in report.get("summary", []):
            v = self.controller.fmt(s["value"]) if s.get("money") else str(s["value"])
            parts.append(f"{s['label']}: {v}")
        self.summary.setText(report["title"] + " - " + report.get("subtitle", "")
                             + "\n" + "    ".join(parts))

    # -- export -------------------------------------------------------
    def _export(self, fmt: str) -> None:
        if not self._report:
            return
        ok, msg, path = self.controller.export(self._report, fmt)
        if ok:
            QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Export failed", msg)

    def _print(self) -> None:
        if not self._report:
            return
        ok, msg, path = self.controller.export(self._report, "pdf")
        if ok:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Could not print", msg)
