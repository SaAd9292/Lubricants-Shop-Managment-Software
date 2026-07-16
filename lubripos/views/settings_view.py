"""Company & Tax settings page — the white-label control center.

Organised as a tabbed screen: Shop, Currency & Invoice, Display, Tax, Payment
Accounts, Updates, and Danger Zone. Editing shop_name here changes the app
title, login screen, and every invoice automatically. Admin-only (this screen is
in ADMIN_ONLY_SCREENS).

The Danger Zone tab flushes all shop data (products, suppliers, purchases, sales,
expenses, audit log) for a fresh start, keeping users, settings and the
category/brand lists — with an automatic safety backup first.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..app_context import AppContext
from ..core.session import current_session
from .payment_accounts_dialog import PaymentAccountsDialog


class SettingsView(QWidget):
    def __init__(self, ctx: AppContext, on_saved=None, on_check_updates=None) -> None:
        super().__init__()
        self.ctx = ctx
        self._on_saved = on_saved
        self._on_check_updates = on_check_updates
        self._build_ui()
        self._load()

    # -- UI -----------------------------------------------------------
    def _scrolled(self, w: QWidget) -> QScrollArea:
        """Wrap a tab's content in a scroll area so it stays usable on small
        windows."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setWidget(w)
        return sa

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(14)
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        # ---- Shop tab ----
        shop = QWidget()
        shop_form = QFormLayout(shop)
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
        self._logo_path = ""
        self.logo_lbl = QLabel("(none)")
        self.logo_lbl.setObjectName("Muted")
        logo_row = QWidget()
        lr = QHBoxLayout(logo_row)
        lr.setContentsMargins(0, 0, 0, 0)
        choose_logo = QPushButton("Choose…")
        choose_logo.setObjectName("Secondary")
        choose_logo.clicked.connect(self._choose_logo)
        clear_logo = QPushButton("Clear")
        clear_logo.setObjectName("Secondary")
        clear_logo.clicked.connect(lambda: self._set_logo(""))
        lr.addWidget(self.logo_lbl, 1)
        lr.addWidget(choose_logo)
        lr.addWidget(clear_logo)
        shop_form.addRow("Logo (on receipt)", logo_row)
        self.tabs.addTab(self._scrolled(shop), "Shop")

        # ---- Currency & Invoice tab ----
        cur = QWidget()
        cur_form = QFormLayout(cur)
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
        self.tabs.addTab(self._scrolled(cur), "Currency & Invoice")

        # ---- Display tab ----
        disp = QWidget()
        disp_form = QFormLayout(disp)
        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("اردو (Urdu)", "ur")
        self.touch_mode = QCheckBox(
            "Touchscreen mode (show an on-screen number pad on the Sale screen)")
        disp_form.addRow("Language", self.language)
        disp_form.addRow("", self.touch_mode)
        disp_hint = QLabel("Urdu covers the counter screens (Sale, menu, receipt). "
                           "A language change applies after you log out and back in.")
        disp_hint.setWordWrap(True)
        disp_hint.setObjectName("Muted")
        disp_form.addRow("", disp_hint)
        self.tabs.addTab(self._scrolled(disp), "Display")

        # ---- Tax tab ----
        tax = QWidget()
        tax_form = QFormLayout(tax)
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
        self.tabs.addTab(self._scrolled(tax), "Tax")

        # ---- Payment Accounts tab ----
        pay = QWidget()
        pay_lay = QVBoxLayout(pay)
        pay_hint = QLabel(
            "Manage the shop's Bank / EasyPaisa / JazzCash accounts. The cashier "
            "picks one at checkout, and the day-close report totals money received "
            "per account.")
        pay_hint.setWordWrap(True)
        pay_hint.setObjectName("Muted")
        pay_lay.addWidget(pay_hint)
        pay_row = QHBoxLayout()
        manage_btn = QPushButton("Manage payment accounts…")
        manage_btn.setObjectName("Secondary")
        manage_btn.clicked.connect(self._manage_payment_accounts)
        pay_row.addWidget(manage_btn)
        pay_row.addStretch(1)
        pay_lay.addLayout(pay_row)
        pay_lay.addStretch(1)
        self.tabs.addTab(self._scrolled(pay), "Payment Accounts")

        # ---- Updates tab (admin-only screen) ----
        upd = QWidget()
        upd_lay = QVBoxLayout(upd)
        upd_lay.addWidget(QLabel(f"Penguix version {__version__}"))
        upd_row = QHBoxLayout()
        self.check_upd_btn = QPushButton("Check for updates")
        self.check_upd_btn.setObjectName("Secondary")
        self.check_upd_btn.clicked.connect(self._check_updates_clicked)
        upd_row.addWidget(self.check_upd_btn)
        upd_row.addStretch(1)
        upd_lay.addLayout(upd_row)
        upd_hint = QLabel("Only administrators can update the software. Updates are "
                          "verified before installing and never touch your shop data.")
        upd_hint.setWordWrap(True)
        upd_hint.setObjectName("Muted")
        upd_lay.addWidget(upd_hint)
        upd_lay.addStretch(1)
        self.tabs.addTab(self._scrolled(upd), "Updates")

        # ---- Danger Zone tab ----
        dz = QWidget()
        dz_lay = QVBoxLayout(dz)
        warn = QLabel(
            "Flush all shop data for a fresh start. Products, suppliers, "
            "purchases, sales, expenses and the audit log are permanently "
            "deleted, and the invoice number resets to 1. Users, settings, and "
            "your category/brand lists are KEPT. A safety backup is taken first "
            "so this can be undone from Backup & Restore.")
        warn.setWordWrap(True)
        warn.setObjectName("Muted")
        dz_lay.addWidget(warn)
        flush_row = QHBoxLayout()
        flush_btn = QPushButton("Flush all data…")
        flush_btn.setObjectName("Danger")
        flush_btn.clicked.connect(self._flush)
        flush_row.addWidget(flush_btn)
        flush_row.addStretch(1)
        dz_lay.addLayout(flush_row)
        dz_lay.addStretch(1)
        self.tabs.addTab(self._scrolled(dz), "Danger Zone")

        # ---- global save (applies to Shop / Currency / Display / Tax) ----
        actions = QHBoxLayout()
        actions.addStretch(1)
        save = QPushButton("Save settings")
        save.setObjectName("Success")
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
        self._set_logo(c.get("logo_path") or "")
        self.currency_code.setText(c.get("currency_code") or "PKR")
        self.currency_symbol.setText(c.get("currency_symbol") or "Rs")
        idx = self.minor_units.findData(c.get("currency_minor_units", 100))
        self.minor_units.setCurrentIndex(max(0, idx))
        self.invoice_prefix.setText(c.get("invoice_prefix") or "INV")
        self.invoice_footer.setText(c.get("invoice_footer") or "")
        self._orig_language = c.get("language") or "en"
        self.language.setCurrentIndex(max(0, self.language.findData(self._orig_language)))
        self.touch_mode.setChecked(bool(c.get("touch_mode", 0)))

        t = self.ctx.company.get_tax()
        self.tax_enabled.setChecked(bool(t.get("tax_enabled", 1)))
        self.tax_label.setText(t.get("tax_label") or "GST")
        self.tax_rate.setValue((t.get("tax_rate_bps", 0)) / 100.0)
        self.tax_inclusive.setChecked(bool(t.get("tax_inclusive", 0)))

    def _save(self) -> None:
        if not self.shop_name.text().strip():
            QMessageBox.warning(self, "Required", "Shop name cannot be empty.")
            self.tabs.setCurrentIndex(0)
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
            "logo_path": self._logo_path,
            "currency_code": self.currency_code.text().strip() or "PKR",
            "currency_symbol": self.currency_symbol.text().strip() or "Rs",
            "currency_minor_units": self.minor_units.currentData(),
            "invoice_prefix": self.invoice_prefix.text().strip() or "INV",
            "invoice_footer": self.invoice_footer.text().strip(),
            "language": self.language.currentData(),
            "touch_mode": 1 if self.touch_mode.isChecked() else 0,
        }, user_id=uid)

        self.ctx.company.update_tax({
            "tax_enabled": 1 if self.tax_enabled.isChecked() else 0,
            "tax_label": self.tax_label.text().strip() or "GST",
            "tax_rate_bps": int(round(self.tax_rate.value() * 100)),
            "tax_inclusive": 1 if self.tax_inclusive.isChecked() else 0,
        }, user_id=uid)

        if self.language.currentData() != getattr(self, "_orig_language", "en"):
            QMessageBox.information(
                self, "Saved",
                "Settings updated. Log out and back in to apply the new language.")
            self._orig_language = self.language.currentData()
        else:
            QMessageBox.information(self, "Saved", "Settings updated.")
        if self._on_saved:
            self._on_saved()

    def _check_updates_clicked(self) -> None:
        if self._on_check_updates:
            self._on_check_updates()

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose shop logo", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self._set_logo(path)

    def _set_logo(self, path: str) -> None:
        self._logo_path = path or ""
        self.logo_lbl.setText(os.path.basename(path) if path else "(none)")

    def _manage_payment_accounts(self) -> None:
        PaymentAccountsDialog(self.ctx, self).exec()

    # -- danger zone --------------------------------------------------
    def _flush(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Flush all data",
            "This permanently deletes all products, suppliers, purchases, sales, "
            "expenses and the audit log.\n\nUsers, settings, and your category / "
            "brand lists are kept, and a safety backup is taken first.\n\n"
            "Type FLUSH to confirm:")
        if not ok or text.strip().upper() != "FLUSH":
            return
        try:
            user = current_session.require_role("admin")
        except Exception as exc:
            QMessageBox.warning(self, "Not allowed", str(exc))
            return
        try:
            safety = self.ctx.backup.flush_shop_data(user_id=user.id)
        except Exception as exc:
            QMessageBox.warning(self, "Flush failed", f"Could not flush data: {exc}")
            return
        QMessageBox.information(
            self, "Data flushed",
            "All shop data was cleared. A safety backup was saved to:\n"
            f"{safety}\n\nPlease restart Penguix to load the clean state.")
        if self._on_saved:
            self._on_saved()
