"""Company & Tax settings page — the white-label control center.

Editing shop_name here changes the app title, login screen, and every
invoice automatically. Nothing about the shop is hardcoded.
Admin-only (enforced by the main window's menu and re-checked here).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.session import current_session


class SettingsView(QWidget):
    def __init__(self, ctx: AppContext, on_saved=None) -> None:
        super().__init__()
        self.ctx = ctx
        self._on_saved = on_saved
        self._build_ui()
        self._load()

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel("Shop & Tax Settings")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        scroll.setWidget(host)
        col = QVBoxLayout(host)
        col.setSpacing(16)
        outer.addWidget(scroll, 1)

        # --- Shop identity ---
        shop_box = QGroupBox("Shop Identity")
        shop_form = QFormLayout(shop_box)
        self.shop_name = QLineEdit()
        self.owner_name = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.address = QPlainTextEdit()
        self.address.setFixedHeight(70)
        self.ntn = QLineEdit()
        self.gst = QLineEdit()
        shop_form.addRow("Shop name *", self.shop_name)
        shop_form.addRow("Owner name", self.owner_name)
        shop_form.addRow("Phone", self.phone)
        shop_form.addRow("Email", self.email)
        shop_form.addRow("Address", self.address)
        shop_form.addRow("NTN number", self.ntn)
        shop_form.addRow("GST number", self.gst)
        col.addWidget(shop_box)

        # --- Currency & invoice ---
        cur_box = QGroupBox("Currency & Invoice")
        cur_form = QFormLayout(cur_box)
        self.currency_code = QLineEdit()
        self.currency_symbol = QLineEdit()
        self.minor_units = QComboBox()
        self.minor_units.addItem("2 decimals (1.00)", 100)
        self.minor_units.addItem("0 decimals (whole)", 1)
        self.minor_units.addItem("3 decimals (1.000)", 1000)
        self.invoice_prefix = QLineEdit()
        self.invoice_footer = QLineEdit()
        cur_form.addRow("Currency code", self.currency_code)
        cur_form.addRow("Currency symbol", self.currency_symbol)
        cur_form.addRow("Decimal precision", self.minor_units)
        cur_form.addRow("Invoice prefix", self.invoice_prefix)
        cur_form.addRow("Invoice footer", self.invoice_footer)
        col.addWidget(cur_box)

        # --- Tax ---
        tax_box = QGroupBox("Tax")
        tax_form = QFormLayout(tax_box)
        self.tax_enabled = QCheckBox("Apply tax on sales")
        self.tax_label = QLineEdit()
        self.tax_rate = QDoubleSpinBox()
        self.tax_rate.setRange(0, 100)
        self.tax_rate.setDecimals(2)
        self.tax_rate.setSuffix(" %")
        self.tax_inclusive = QCheckBox("Prices already include tax (inclusive)")
        tax_form.addRow("", self.tax_enabled)
        tax_form.addRow("Tax label", self.tax_label)
        tax_form.addRow("Tax rate", self.tax_rate)
        tax_form.addRow("", self.tax_inclusive)
        col.addWidget(tax_box)
        col.addStretch(1)

        # --- Actions ---
        actions = QHBoxLayout()
        actions.addStretch(1)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save)
        actions.addWidget(save)
        outer.addLayout(actions)

    # -- data ---------------------------------------------------------
    def _load(self) -> None:
        c = self.ctx.company.get_company()
        self.shop_name.setText(c.get("shop_name", ""))
        self.owner_name.setText(c.get("owner_name") or "")
        self.phone.setText(c.get("phone") or "")
        self.email.setText(c.get("email") or "")
        self.address.setPlainText(c.get("address") or "")
        self.ntn.setText(c.get("ntn_number") or "")
        self.gst.setText(c.get("gst_number") or "")
        self.currency_code.setText(c.get("currency_code") or "PKR")
        self.currency_symbol.setText(c.get("currency_symbol") or "Rs")
        idx = self.minor_units.findData(c.get("currency_minor_units", 100))
        self.minor_units.setCurrentIndex(max(0, idx))
        self.invoice_prefix.setText(c.get("invoice_prefix") or "INV")
        self.invoice_footer.setText(c.get("invoice_footer") or "")

        t = self.ctx.company.get_tax()
        self.tax_enabled.setChecked(bool(t.get("tax_enabled", 1)))
        self.tax_label.setText(t.get("tax_label") or "GST")
        self.tax_rate.setValue((t.get("tax_rate_bps", 0)) / 100.0)
        self.tax_inclusive.setChecked(bool(t.get("tax_inclusive", 0)))

    def _save(self) -> None:
        if not self.shop_name.text().strip():
            QMessageBox.warning(self, "Required", "Shop name cannot be empty.")
            return
        user = current_session.user
        uid = user.id if user else None

        self.ctx.company.update_company({
            "shop_name": self.shop_name.text().strip(),
            "owner_name": self.owner_name.text().strip(),
            "phone": self.phone.text().strip(),
            "email": self.email.text().strip(),
            "address": self.address.toPlainText().strip(),
            "ntn_number": self.ntn.text().strip(),
            "gst_number": self.gst.text().strip(),
            "currency_code": self.currency_code.text().strip() or "PKR",
            "currency_symbol": self.currency_symbol.text().strip() or "Rs",
            "currency_minor_units": self.minor_units.currentData(),
            "invoice_prefix": self.invoice_prefix.text().strip() or "INV",
            "invoice_footer": self.invoice_footer.text().strip(),
        }, user_id=uid)

        self.ctx.company.update_tax({
            "tax_enabled": 1 if self.tax_enabled.isChecked() else 0,
            "tax_label": self.tax_label.text().strip() or "GST",
            "tax_rate_bps": int(round(self.tax_rate.value() * 100)),
            "tax_inclusive": 1 if self.tax_inclusive.isChecked() else 0,
        }, user_id=uid)

        QMessageBox.information(self, "Saved", "Settings updated.")
        if self._on_saved:
            self._on_saved()
