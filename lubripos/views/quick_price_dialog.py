"""Quick price update — a tiny pop-up for changing a product's sale price in a
couple of keystrokes WITHOUT leaving the current screen.

Flow: scan the barcode or type the product name → Enter → it shows the current
sale price and pre-fills the new one → type the new price → Enter → saved, ready
for the next one. Built standalone so the same dialog can be opened from the
Back-date form today and the POS later (just open it with the AppContext).

Writing a price is an edit, so it needs the 'Edit records' privilege (admins
always have it); ProductController enforces that.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCompleter, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.product_controller import ProductController
from ..core.session import current_session
from ..ui.toast import show_toast


class QuickPriceDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = ProductController(ctx)
        self._sym, self._mu = self.controller.currency()
        self._index: dict[str, dict] = {}     # name.lower -> product row
        self._product: dict | None = None
        self.setWindowTitle("Quick price update")
        self.setMinimumWidth(460)
        self._build_ui()
        self._refresh_products()
        self.prod.setFocus()

    # -- ui -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        hint = QLabel("Scan the barcode or type the product name, press Enter, "
                      "then type the new price and press Enter.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.prod = QLineEdit()
        self.prod.setPlaceholderText("Scan barcode or type product name…")
        self._suggest = QCompleter(self)
        self._suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._suggest.setFilterMode(Qt.MatchContains)
        self._suggest.setCompletionMode(QCompleter.PopupCompletion)
        self.prod.setCompleter(self._suggest)
        self._suggest.activated[str].connect(self._resolve_by_name)
        self.prod.installEventFilter(self)
        form.addRow("Product", self.prod)

        self.current_lbl = QLabel("—")
        self.current_lbl.setStyleSheet("font-weight:700;")
        form.addRow("Current price", self.current_lbl)

        self.new_price = QDoubleSpinBox()
        self.new_price.setRange(0, 1_000_000_000)
        self.new_price.setDecimals(max(0, len(str(self._mu or 100)) - 1))
        self.new_price.setGroupSeparatorShown(True)
        self.new_price.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.new_price.setPrefix(f"{self._sym} ")
        self.new_price.setEnabled(False)
        self.new_price.installEventFilter(self)
        form.addRow("New price", self.new_price)
        root.addLayout(form)

        bar = QHBoxLayout()
        bar.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self.reject)
        bar.addWidget(close)
        self.next_btn = QPushButton("Save && next")
        self.next_btn.setObjectName("Secondary")
        self.next_btn.clicked.connect(lambda: self._save(keep_open=True))
        self.next_btn.setEnabled(False)
        bar.addWidget(self.next_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("Success")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.clicked.connect(lambda: self._save(keep_open=False))
        self.save_btn.setEnabled(False)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

    # -- product lookup ----------------------------------------------
    def _refresh_products(self) -> None:
        try:
            rows = self.controller.list(search="", limit=100000)["rows"]
        except Exception:
            rows = []
        self._index = {}
        names: list[str] = []
        for p in rows:
            key = (p.get("name") or "").lower()
            if key and key not in self._index:
                self._index[key] = p
                names.append(p["name"])
        self._suggest.setModel(QStringListModel(names, self._suggest))

    def _resolve_by_name(self, text: str) -> None:
        self._take(self._index.get((text or "").strip().lower()))

    def _resolve(self) -> None:
        """Enter in the product box: try an exact barcode first, then the name."""
        term = self.prod.text().strip()
        if not term:
            return
        p = None
        try:
            p = self.controller.find_by_barcode(term)
        except Exception:
            p = None
        if p is None:
            p = self._index.get(term.lower())
        if p is None:
            QMessageBox.information(self, "Not found",
                                    f"No product matched '{term}'.")
            self.prod.selectAll()
            return
        self._take(p)

    def _take(self, p: dict | None) -> None:
        self._product = p
        if not p:
            self.current_lbl.setText("—")
            self.new_price.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        self.prod.setText(p.get("name") or "")
        cur = int(p.get("sale_price_minor") or 0)
        self.current_lbl.setText(self.controller.fmt(cur))
        self.new_price.setEnabled(True)
        self.new_price.setValue(cur / (self._mu or 100))
        self.save_btn.setEnabled(True)
        self.next_btn.setEnabled(True)
        self.new_price.setFocus()
        self.new_price.selectAll()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if event.type() == QEvent.KeyPress and event.key() in (
                Qt.Key_Return, Qt.Key_Enter):
            if obj is self.prod:
                self._resolve()
                return True
            if obj is self.new_price and self._product:
                self._save(keep_open=False)
                return True
        return super().eventFilter(obj, event)

    # -- save ---------------------------------------------------------
    def _save(self, *, keep_open: bool) -> None:
        if not self._product:
            return
        if not current_session.can("record.edit"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the Edit records privilege.")
            return
        ok, msg, _ = self.controller.save(
            {"sale_price": self.new_price.value()}, self._product["id"])
        if not ok:
            QMessageBox.warning(self, "Could not update price", msg)
            return
        # anchor the toast to the PARENT window (not this dialog) — on a closing
        # save the dialog is destroyed and a toast parented to it would fire its
        # timer on a deleted window, which the app would report as a crash
        show_toast(self.parentWidget() or self,
                   f"Price updated — {self._product.get('name')}")
        self._refresh_products()          # keep the index fresh
        if keep_open:
            self._product = None
            self.prod.clear()
            self.current_lbl.setText("—")
            self.new_price.setValue(0)
            self.new_price.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.prod.setFocus()
        else:
            self.accept()
