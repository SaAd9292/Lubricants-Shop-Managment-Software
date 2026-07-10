"""Sales History: list, filter, view invoice, and (admin) void sales."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..app_context import AppContext
from ..ui.widgets import DataTable
from ..controllers.sale_controller import SaleController
from ..core.session import current_session
from .sale_receipt_dialog import SaleReceiptDialog

PAGE_SIZE = 25
COLUMNS = ["Invoice", "Date", "Cashier", "Items", "Total", "Status"]


class SalesView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SaleController(ctx)
        self._page = 0
        self._total = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reset_and_reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel("Sales History")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search invoice no…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_status = QComboBox()
        self.f_status.addItem("All", None)
        self.f_status.addItem("Completed", "completed")
        self.f_status.addItem("Void", "void")
        self.f_status.currentIndexChanged.connect(self._reset_and_reload)

        # Optional date-range filter. Off by default (shows all sales); when
        # ticked, only sales whose date falls in [from, to] are listed.
        self.f_bydate = QCheckBox("By date")
        self.f_bydate.stateChanged.connect(self._on_date_toggle)
        self.f_from = QDateEdit(QDate.currentDate().addDays(-30))
        self.f_to = QDateEdit(QDate.currentDate())
        for de in (self.f_from, self.f_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setEnabled(False)
            de.dateChanged.connect(self._reset_and_reload)

        filters.addWidget(self.search, 1)
        filters.addWidget(QLabel("Status:"))
        filters.addWidget(self.f_status)
        filters.addWidget(self.f_bydate)
        filters.addWidget(QLabel("From:"))
        filters.addWidget(self.f_from)
        filters.addWidget(QLabel("To:"))
        filters.addWidget(self.f_to)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = 'No sales yet - completed sales will appear here.'
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._view)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        view_btn = QPushButton("View invoice")
        view_btn.setObjectName("Secondary")
        view_btn.clicked.connect(self._view)
        footer.addWidget(view_btn)
        pdf_btn = QPushButton("Print / PDF")
        pdf_btn.setObjectName("Secondary")
        pdf_btn.clicked.connect(self._print)
        footer.addWidget(pdf_btn)
        self.void_btn = QPushButton("Void sale")
        self.void_btn.setObjectName("Secondary")
        self.void_btn.clicked.connect(self._void)
        self.void_btn.setEnabled(current_session.is_admin)
        if not current_session.is_admin:
            self.void_btn.setToolTip("Admin only")
        footer.addWidget(self.void_btn)
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
            search=self.search.text(),
            status=self.f_status.currentData(),
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
        for r, s in enumerate(rows):
            values = [
                s["invoice_no"], (s.get("sale_date") or "")[:16],
                s.get("cashier_name") or "—", str(s.get("line_count", 0)),
                self.controller.fmt(s["grand_total_minor"]), s["status"],
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c in (3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, s["id"])
                if s["status"] == "void":
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} sales)")
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

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    # -- actions ------------------------------------------------------
    def _view(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Select a sale", "Please select a row first.")
            return
        SaleReceiptDialog(self.ctx, sid).exec()

    def _print(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Select a sale", "Please select a row first.")
            return
        ok, msg, out = self.controller.generate_pdf(sid)
        if not ok:
            QMessageBox.warning(self, "Could not create PDF", msg)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _void(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Select a sale", "Please select a row first.")
            return
        confirm = QMessageBox.question(
            self, "Void sale",
            "Void this sale? Stock will be restored and the sale marked void. "
            "This cannot be undone.",
        )
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.void(sid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not void", msg)
