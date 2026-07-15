"""On-screen receipt / invoice preview with Save PDF and Print actions."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.sale_controller import SaleController
from ..core import money
from ..services.sale_service import SaleService


class SaleReceiptDialog(QDialog):
    def __init__(self, ctx: AppContext, sale_id: int) -> None:
        super().__init__()
        self.ctx = ctx
        self.sale_id = sale_id
        self.controller = SaleController(ctx)
        self._company = ctx.company.get_company()
        self._symbol = self._company.get("currency_symbol", "Rs")
        self._mu = self._company.get("currency_minor_units", 100)
        self._sale = SaleService(ctx.db).get_sale(sale_id)
        self.setWindowTitle(f"Invoice {self._sale['invoice_no']}")
        self.setMinimumSize(460, 600)
        self._build_ui()

    def _fmt(self, minor: int) -> str:
        return money.format_money(minor, self._symbol, self._mu)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(8)

        shop = QLabel(self._company.get("shop_name") or "Penguix")
        shop.setAlignment(Qt.AlignCenter)
        shop.setStyleSheet("font-size: 20px; font-weight: 800;")
        root.addWidget(shop)
        meta_bits = []
        if self._company.get("address"):
            meta_bits.append(self._company["address"])
        if self._company.get("phone"):
            meta_bits.append("Tel: " + self._company["phone"])
        if meta_bits:
            sub = QLabel("\n".join(meta_bits))
            sub.setObjectName("Muted")
            sub.setAlignment(Qt.AlignCenter)
            root.addWidget(sub)

        s = self._sale
        cust = s.get("customer_name")
        cust_html = f"<br><b>Customer:</b> {cust}" if cust else ""
        info = QLabel(
            f"<b>Invoice:</b> {s['invoice_no']} &nbsp;&nbsp; "
            f"<b>Status:</b> {s['status']}<br>"
            f"<b>Date:</b> {(s.get('sale_date') or '')[:16]}<br>"
            f"<b>Cashier:</b> {s.get('cashier_name') or '-'} &nbsp;&nbsp; "
            f"<b>Payment:</b> {s.get('payment_method') or '-'}"
            f"{cust_html}"
        )
        info.setTextFormat(Qt.RichText)
        root.addWidget(info)

        items = s.get("items", [])
        table = QTableWidget(len(items), 4)
        table.setHorizontalHeaderLabels(["Item", "Qty", "Price", "Total"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for r, it in enumerate(items):
            cells = [it["product_name"], str(it["qty"]),
                     self._fmt(it["unit_price_minor"]), self._fmt(it["line_total_minor"])]
            for c, val in enumerate(cells):
                cell = QTableWidgetItem(val)
                if c in (1, 2, 3):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, cell)
        root.addWidget(table, 1)

        self._total_row(root, "Subtotal", self._fmt(s["subtotal_minor"]))
        if s["discount_minor"]:
            self._total_row(root, "Discount", "- " + self._fmt(s["discount_minor"]))
        if s["tax_minor"]:
            label = f"{s.get('tax_label','Tax')} {s['tax_rate_bps']/100:.2f}%"
            self._total_row(root, label, self._fmt(s["tax_minor"]))
        self._total_row(root, "Grand Total", self._fmt(s["grand_total_minor"]), big=True)
        if (s.get("payment_method") == "Cash") and s.get("amount_paid_minor"):
            self._total_row(root, "Paid", self._fmt(s["amount_paid_minor"]))
            change = max(0, s["amount_paid_minor"] - s["grand_total_minor"])
            self._total_row(root, "Change", self._fmt(change))

        footer = QLabel(self._company.get("invoice_footer") or "Thank you!")
        footer.setAlignment(Qt.AlignCenter)
        footer.setObjectName("Muted")
        root.addWidget(footer)

        actions = QHBoxLayout()
        save_btn = QPushButton("Save PDF")
        save_btn.setObjectName("Secondary")
        save_btn.clicked.connect(self._save_pdf)
        print_btn = QPushButton("Print")
        print_btn.clicked.connect(self._print)
        actions.addWidget(save_btn)
        actions.addWidget(print_btn)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)

    def _total_row(self, root: QVBoxLayout, label: str, value: str, big: bool = False) -> None:
        row = QHBoxLayout()
        k = QLabel(label)
        v = QLabel(value)
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if big:
            k.setStyleSheet("font-weight:700; font-size:16px;")
            v.setStyleSheet("font-weight:800; font-size:18px;")
        row.addWidget(k)
        row.addStretch(1)
        row.addWidget(v)
        root.addLayout(row)

    # -- PDF actions --------------------------------------------------
    def _save_pdf(self) -> None:
        default = str(self.controller.invoices.default_path(self._sale["invoice_no"]))
        path, _ = QFileDialog.getSaveFileName(self, "Save invoice PDF", default, "PDF (*.pdf)")
        if not path:
            return
        ok, msg, out = self.controller.generate_pdf(self.sale_id, dest=path)
        if ok:
            QMessageBox.information(self, "Saved", f"Invoice saved to:\n{out}")
        else:
            QMessageBox.warning(self, "Could not save", msg)

    def _print(self) -> None:
        """Generate the PDF and open it in the system viewer, where the user can print."""
        ok, msg, out = self.controller.generate_pdf(self.sale_id)
        if not ok:
            QMessageBox.warning(self, "Could not create PDF", msg)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))
