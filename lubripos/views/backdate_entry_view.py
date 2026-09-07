"""Back-date Entry: a fast, keyboard-driven form for keying old paper bills.

Built for volume and for the keyboard — the operator never needs the mouse.
Pressing Enter walks the focus down the fields in order:

    Day → Month → Year → Payment → Customer → Product → Qty → Amount

Enter on Amount adds the line to the bill and jumps back to Product for the next
item; Enter on an empty Product box saves the whole bill (Ctrl+Enter also saves,
Esc-style Reset clears it). Every bill is recorded on its real date via
SaleController.record_backdated_sale, which decrements stock without blocking on
shortfalls (a short line goes negative until its purchase is keyed) and reports
any short line. Admin-only; only ever mounted inside the Admin Panel.
"""
from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, Qt, QStringListModel
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QCompleter, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core import money
from ..core.i18n import tr
from ..controllers.sale_controller import SaleController
from ..ui.widgets import DataTable, enable_tabular_figures, number_rows

CART_COLS = ["Product", "Qty", "Amount", "Line total", ""]

# (display label, stored payment_method value)
PAYMENT_METHODS = [
    ("Cash", "Cash"),
    ("Bank / transfer", "Bank"),
    ("EasyPaisa", "EasyPaisa"),
    ("JazzCash", "JazzCash"),
    ("Credit / Udhaar", "Debt"),
]


class BackdateEntryView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = SaleController(ctx)
        self._cart: list[dict] = []          # {product_id, name, qty, up_minor}
        self._name_index: dict[str, dict] = {}
        self._cust_index: dict[str, dict] = {}    # name.lower -> {id, name, phone}
        self._watch: dict[object, QWidget] = {}   # focus-chain event routing
        self._build_ui()
        self._refresh_products()
        self._refresh_customers()

    # -- ui -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(12)

        title = QLabel(tr("Past-Date Sale"))
        title.setObjectName("PageTitle")
        root.addWidget(title)
        hint = QLabel(tr("Press Enter to move to the next field. Enter on Amount "
                         "adds the item; Enter on an empty Product box (or "
                         "Ctrl+Enter) saves the bill. Stock reduces as normal; a "
                         "short line goes negative and is flagged."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        today = QDate.currentDate()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # Date: D / M / Y steppers
        self.d_day = QSpinBox(); self.d_day.setRange(1, 31); self.d_day.setValue(today.day())
        self.d_month = QSpinBox(); self.d_month.setRange(1, 12); self.d_month.setValue(today.month())
        self.d_year = QSpinBox(); self.d_year.setRange(2000, today.year()); self.d_year.setValue(today.year())
        date_row = QHBoxLayout()
        for w, ph in ((self.d_day, "D"), (self.d_month, "M"), (self.d_year, "Y")):
            w.setPrefix(tr(ph) + " ")
            w.setMaximumWidth(90)
            date_row.addWidget(w)
        date_row.addStretch(1)
        date_wrap = QWidget(); date_wrap.setLayout(date_row)
        form.addRow(tr("Date"), date_wrap)

        # Payment method
        self.method = QComboBox()
        for label, value in PAYMENT_METHODS:
            self.method.addItem(tr(label), value)
        self.method.currentIndexChanged.connect(self._on_method_changed)
        form.addRow(tr("Payment"), self.method)

        # Customer (type-ahead over saved customers; required only for credit)
        self.cust_name = QLineEdit()
        self.cust_name.setPlaceholderText(tr("Walk-in — type to find a saved customer"))
        self._cust_suggest = QCompleter(self)
        self._cust_suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._cust_suggest.setFilterMode(Qt.MatchContains)
        self._cust_suggest.setCompletionMode(QCompleter.PopupCompletion)
        self._cust_suggest.setMaxVisibleItems(10)
        self.cust_name.setCompleter(self._cust_suggest)
        self._cust_suggest.activated[str].connect(self._on_cust_pick)
        form.addRow(tr("Customer"), self.cust_name)

        # Description / paper bill number (optional; searchable in Sales History)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText(tr("Paper/bill number or note (optional)"))
        form.addRow(tr("Description"), self.notes)

        # Product (type-ahead)
        self.prod = QLineEdit()
        self.prod.setPlaceholderText(tr("Type product name…"))
        self._suggest = QCompleter(self)
        self._suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._suggest.setFilterMode(Qt.MatchContains)
        self._suggest.setCompletionMode(QCompleter.PopupCompletion)
        self._suggest.setMaxVisibleItems(10)
        self.prod.setCompleter(self._suggest)
        self._suggest.activated[str].connect(self._on_pick)
        form.addRow(tr("Product"), self.prod)

        # Qty
        self.qty = QSpinBox()
        self.qty.setRange(1, 1_000_000)
        self.qty.setButtonSymbols(QAbstractSpinBox.NoButtons)
        form.addRow(tr("Qty"), self.qty)

        # Amount (price each)
        sym, _ = self.controller.currency()
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 100_000_000)
        self.price.setDecimals(2)
        self.price.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.price.setPrefix(f"{sym} ")
        amount_row = QHBoxLayout()
        amount_row.addWidget(self.price, 1)
        add_btn = QPushButton(tr("Add item"))
        add_btn.clicked.connect(self._add_line)
        amount_row.addWidget(add_btn)
        amount_wrap = QWidget(); amount_wrap.setLayout(amount_row)
        form.addRow(tr("Amount (each)"), amount_wrap)
        root.addLayout(form)

        # cart of items on this bill
        self.cart = DataTable(0, len(CART_COLS))
        self.cart.placeholder = tr("No items yet — add products above.")
        self.cart.setHorizontalHeaderLabels([tr(c) for c in CART_COLS])
        self.cart.verticalHeader().setVisible(True)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cart.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cart.setColumnWidth(4, 40)
        self.cart.cellClicked.connect(self._on_cell)
        enable_tabular_figures(self.cart)
        root.addWidget(self.cart, 1)

        # discount + total
        foot = QHBoxLayout()
        foot.addWidget(QLabel(tr("Discount:")))
        self.discount = QDoubleSpinBox()
        self.discount.setRange(0, 100_000_000)
        self.discount.setDecimals(2)
        self.discount.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.discount.setPrefix(f"{sym} ")
        self.discount.setMaximumWidth(160)
        self.discount.valueChanged.connect(self._update_totals)
        foot.addWidget(self.discount)
        foot.addStretch(1)
        self.lbl_total = QLabel("")
        self.lbl_total.setObjectName("PageTitle")
        enable_tabular_figures(self.lbl_total)
        foot.addWidget(self.lbl_total)
        root.addLayout(foot)

        # status + Save / Reset
        actions = QHBoxLayout()
        self.flash = QLabel("")
        self.flash.setWordWrap(True)
        actions.addWidget(self.flash, 1)
        self.reset_btn = QPushButton(tr("Reset"))
        self.reset_btn.setObjectName("Secondary")
        self.reset_btn.clicked.connect(self._reset)
        actions.addWidget(self.reset_btn)
        self.save_btn = QPushButton(tr("Save bill  (Ctrl+Enter)"))
        self.save_btn.setMinimumHeight(40)
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(self.save_btn)
        root.addLayout(actions)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._save)

        # Enter-to-advance focus chain (no mouse required)
        self._chain = [self.d_day, self.d_month, self.d_year, self.method,
                       self.cust_name, self.prod, self.qty, self.price]
        for w in self._chain:
            self._install_enter(w)

        self._on_method_changed()
        self._update_totals()
        self.d_day.setFocus()

    # -- keyboard focus chain ----------------------------------------
    def _install_enter(self, field: QWidget) -> None:
        """Route Enter on `field` (and its inner line edit, for spin boxes) to
        _advance, so a single handler drives the whole chain."""
        field.installEventFilter(self)
        self._watch[field] = field
        le_getter = getattr(field, "lineEdit", None)
        le = le_getter() if callable(le_getter) else None
        if le is not None:
            le.installEventFilter(self)
            self._watch[le] = field

    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if (event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            field = self._watch.get(obj)
            if field is not None:
                self._advance(field)
                return True
        return super().eventFilter(obj, event)

    def _advance(self, field: QWidget) -> None:
        if field is self.price:
            self._add_line()
            return
        if field is self.prod:
            if not self.prod.text().strip():
                self._save()               # empty product = done adding -> save
                return
            p = self._current_product()
            if p is None:
                self._say(tr("Pick a product from the list first."), error=True)
                return
            self.price.setValue((p.get("sale_price_minor") or 0) / self._mu())
            self.qty.setFocus()
            self.qty.selectAll()
            return
        i = self._chain.index(field)
        if i + 1 < len(self._chain):
            self._focus(self._chain[i + 1])

    @staticmethod
    def _focus(widget: QWidget) -> None:
        widget.setFocus()
        le_getter = getattr(widget, "lineEdit", None)
        le = le_getter() if callable(le_getter) else None
        if le is not None:
            le.selectAll()
        elif hasattr(widget, "selectAll"):
            widget.selectAll()

    # -- header helpers ----------------------------------------------
    def _on_method_changed(self) -> None:
        credit = self.method.currentData() == "Debt"
        self.cust_name.setPlaceholderText(
            tr("Customer name (required)") if credit else tr("Walk-in"))

    def _bill_date(self) -> str | None:
        """Build 'YYYY-MM-DD' from the D/M/Y steppers, or None if the day is not
        valid for that month/year (e.g. 31 Feb) or the date is in the future."""
        d = QDate(self.d_year.value(), self.d_month.value(), self.d_day.value())
        if not d.isValid() or d > QDate.currentDate():
            return None
        return d.toString("yyyy-MM-dd")

    # -- product lookup ----------------------------------------------
    def _refresh_products(self) -> None:
        """(Re)build the type-ahead index of product names."""
        try:
            rows = self.controller.search_products("", None, 100000)
        except TypeError:
            rows = self.controller.search_products("")
        self._name_index = {}
        names: list[str] = []
        for p in rows:
            key = (p["name"] or "").lower()
            if key and key not in self._name_index:
                self._name_index[key] = p
                names.append(p["name"])
        self._suggest.setModel(QStringListModel(names, self._suggest))

    def _refresh_customers(self) -> None:
        """(Re)build the type-ahead index of saved customer names."""
        try:
            rows = self.controller.search_customers("", 100000)
        except TypeError:
            rows = self.controller.search_customers("")
        self._cust_index = {}
        names: list[str] = []
        for c in rows:
            key = (c["name"] or "").lower()
            if key and key not in self._cust_index:
                self._cust_index[key] = c
                names.append(c["name"])
        self._cust_suggest.setModel(QStringListModel(names, self._cust_suggest))

    def _on_cust_pick(self, text: str) -> None:
        """A saved customer was chosen from the type-ahead -> take it and move on."""
        c = self._cust_index.get((text or "").strip().lower())
        if c:
            self.cust_name.setText(c["name"])
            self._focus(self.prod)

    def _resolve_customer_id(self) -> int | None:
        """Match the typed name to a saved customer (exact, case-insensitive)."""
        c = self._cust_index.get(self.cust_name.text().strip().lower())
        return c["id"] if c else None

    def _reload(self) -> None:
        """Nav hook: keep product + customer lists fresh without wiping a bill."""
        self._refresh_products()
        self._refresh_customers()

    def _current_product(self) -> dict | None:
        return self._name_index.get(self.prod.text().strip().lower())

    def _on_pick(self, text: str) -> None:
        p = self._name_index.get((text or "").strip().lower())
        if p:
            self.price.setValue((p.get("sale_price_minor") or 0) / self._mu())
            self.qty.setFocus()
            self.qty.selectAll()

    def _mu(self) -> int:
        _, mu = self.controller.currency()
        return mu or 100

    # -- cart ---------------------------------------------------------
    def _add_line(self) -> None:
        p = self._current_product()
        if p is None:
            self._say(tr("Pick a product from the list first."), error=True)
            self.prod.setFocus()
            return
        mu = self._mu()
        up_minor = money.to_minor(self.price.value(), mu)
        self._cart.append({
            "product_id": p["id"], "name": p["name"],
            "qty": int(self.qty.value()), "up_minor": up_minor,
        })
        self._render_cart()
        self._update_totals()
        # reset the item fields, cursor back on Product for the next item
        self.prod.clear()
        self.qty.setValue(1)
        self.price.setValue(0)
        self.prod.setFocus()

    def _render_cart(self) -> None:
        self.cart.setRowCount(len(self._cart))
        number_rows(self.cart, 1)
        for r, ln in enumerate(self._cart):
            line_minor = ln["qty"] * ln["up_minor"]
            cells = [
                ln["name"], str(ln["qty"]),
                self.controller.fmt(ln["up_minor"]),
                self.controller.fmt(line_minor), "✕",
            ]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(Qt.red)
                self.cart.setItem(r, c, item)

    def _on_cell(self, row: int, col: int) -> None:
        if col == len(CART_COLS) - 1 and 0 <= row < len(self._cart):
            self._cart.pop(row)
            self._render_cart()
            self._update_totals()

    def _subtotal_minor(self) -> int:
        return sum(ln["qty"] * ln["up_minor"] for ln in self._cart)

    def _update_totals(self) -> None:
        sub = self._subtotal_minor()
        disc = money.to_minor(self.discount.value(), self._mu())
        total = max(0, sub - disc)
        self.lbl_total.setText(tr("Total:") + "  " + self.controller.fmt(total))

    # -- save / reset -------------------------------------------------
    def _reset(self) -> None:
        """Clear the whole bill and start fresh (keeps the date + payment so the
        next bill is fast); cursor back to the Day field."""
        self._cart = []
        self.discount.setValue(0)
        self.cust_name.clear()
        self.notes.clear()
        self.prod.clear()
        self.qty.setValue(1)
        self.price.setValue(0)
        self._render_cart()
        self._update_totals()
        self.flash.setText("")
        self.d_day.setFocus()

    def _save(self) -> None:
        if not self._cart:
            self._say(tr("Add at least one product line."), error=True)
            return
        disc = self.discount.value()
        if money.to_minor(disc, self._mu()) > self._subtotal_minor():
            self._say(tr("Discount cannot exceed the subtotal."), error=True)
            return
        sale_date = self._bill_date()
        if sale_date is None:
            self._say(tr("That date is not valid (check the day/month, and it "
                         "cannot be in the future)."), error=True)
            self.d_day.setFocus()
            return
        method = self.method.currentData()
        customer = self.cust_name.text().strip() or None
        if method == "Debt" and not customer:
            self._say(tr("A credit (udhaar) bill needs a customer name."),
                      error=True)
            self.cust_name.setFocus()
            return
        customer_id = self._resolve_customer_id()
        lines = [{"product_id": ln["product_id"], "qty": ln["qty"],
                  "unit_price": ln["up_minor"] / self._mu()} for ln in self._cart]
        ok, msg, summary = self.controller.record_backdated_sale(
            lines=lines, sale_date=sale_date, discount=disc,
            payment_method=method, customer_id=customer_id,
            customer_name=customer, notes=self.notes.text() or None)
        if not ok:
            QMessageBox.warning(self, tr("Bill not saved"), msg)
            return
        inv = summary.get("invoice_no", "")
        total_txt = self.controller.fmt(summary.get("grand_total_minor", 0))
        short = summary.get("short_lines") or []
        note = ""
        if short:
            note = "  " + tr("Stock went negative for: ") + ", ".join(short) + \
                   " " + tr("(it nets back up when that purchase is entered).")
        self._say(tr("Saved bill ") + f"{inv} · {sale_date} · {total_txt}" + note)
        self._refresh_customers()   # a newly-created credit customer is now pickable
        # keep the date + payment for the next bill; clear the rest, back to Product
        self._cart = []
        self.discount.setValue(0)
        self.cust_name.clear()
        self.notes.clear()
        self._render_cart()
        self._update_totals()
        self.prod.clear()
        self.qty.setValue(1)
        self.price.setValue(0)
        self.prod.setFocus()

    def _say(self, text: str, *, error: bool = False) -> None:
        self.flash.setText(text)
        self.flash.setStyleSheet(
            "color:#b91c1c; font-weight:600;" if error else
            "color:#15803d; font-weight:600;")
