"""New Purchase dialog: pick a supplier, add product lines, save.

Layout follows the standard purchase-entry order:
  header (supplier / date / bill no / notes)
  -> keyboard line entry (Product -> Qty[Piece/Carton] -> Unit cost -> Disc -> Add)
  -> cart of added lines
  -> totals (subtotal -> bill discount -> advance tax -> grand total)
  -> amount paid now (defaults to 0 = on credit)

Entry is keyboard-driven, like the Back-date Entry form: Enter moves to the next
field and Enter on the last field (Disc) adds the line and returns to Product.

Saving records the purchase and increases each product's stock atomically
(handled in PurchaseService within a single transaction).
"""
from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QCompleter, QDateEdit, QDialog,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..controllers.purchase_controller import PurchaseController
from ..core import money
from .product_picker_dialog import ProductPickerDialog

CART_COLS = ["Product", "Qty", "Unit cost/pc", "Disc", "Line total", ""]


class NewPurchaseDialog(QDialog):
    def __init__(self, controller: PurchaseController) -> None:
        super().__init__()
        self.controller = controller
        self._symbol, self._minor_units = controller.currency()
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self._cart: list[dict] = []        # {product_id, name, qty, cost_minor, disc_minor}
        self._name_index: dict[str, dict] = {}
        self._grand_minor = 0
        self.setWindowTitle("New Purchase")
        # behave like a normal window: movable, minimize / maximize / close
        # buttons, and freely resizable.
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(900, 560)
        self.resize(1060, 915)
        self._cart_sized = False
        self._build_ui()
        self._refresh_products()

    # how many cart rows are visible before the cart scrolls internally
    _VISIBLE_ROWS = 5

    def showEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        super().showEvent(event)
        # fix the cart to exactly _VISIBLE_ROWS tall now that real row/header
        # heights are known; extra rows then scroll inside the cart itself.
        if not self._cart_sized:
            self._cart_sized = True
            header_h = self.table.horizontalHeader().height() or 30
            row_h = self.table.verticalHeader().defaultSectionSize() or 34
            h = header_h + self._VISIBLE_ROWS * row_h + 4
            self.table.setMinimumHeight(h)
            self.table.setMaximumHeight(h)

    # a consistent, comfortable height for every spin box so none render clipped
    _FIELD_H = 32

    # -- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        # Everything lives inside a scroll area so that, no matter how many lines
        # are added or how small the screen is, the totals and Save button are
        # always reachable by scrolling.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(16)

        title = QLabel("New Purchase")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        hint = QLabel("Enter moves to the next field; Enter on Disc adds the item. "
                      "Select a cart row and press Delete to remove it.")
        hint.setObjectName("Muted")
        root.addWidget(hint)

        # ---- header: supplier / date / bill no / notes ----
        header = QFormLayout()
        header.setHorizontalSpacing(16)
        header.setVerticalSpacing(12)
        self.supplier = QComboBox()
        self.supplier.addItem("— Select supplier —", None)
        for s in self.controller.active_suppliers():
            self.supplier.addItem(s["name"], s["id"])
        header.addRow("Supplier", self.supplier)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setDate(QDate.currentDate())
        self.date.setMaximumDate(QDate.currentDate())
        header.addRow("Date", self.date)
        self.invoice_no = QLineEdit()
        self.invoice_no.setPlaceholderText("Supplier's invoice/bill no (optional)")
        header.addRow("Supplier invoice #", self.invoice_no)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Notes (optional)")
        header.addRow("Notes", self.notes)
        root.addLayout(header)

        # ---- line entry row (keyboard-driven) ----
        entry = QFormLayout()
        entry.setHorizontalSpacing(16)
        entry.setVerticalSpacing(12)
        self.prod = QLineEdit()
        self.prod.setPlaceholderText("Type product name…")
        self._suggest = QCompleter(self)
        self._suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._suggest.setFilterMode(Qt.MatchContains)
        self._suggest.setCompletionMode(QCompleter.PopupCompletion)
        self._suggest.setMaxVisibleItems(10)
        self.prod.setCompleter(self._suggest)
        self._suggest.activated[str].connect(self._on_pick)
        prod_row = QHBoxLayout()
        prod_row.setContentsMargins(0, 0, 0, 0)
        prod_row.addWidget(self.prod, 1)
        browse = QPushButton("Browse…")
        browse.setObjectName("Secondary")
        browse.setToolTip("Browse all products in a list")
        browse.clicked.connect(self._browse_product)
        prod_row.addWidget(browse)
        prod_wrap = QWidget(); prod_wrap.setLayout(prod_row)
        entry.addRow("Product", prod_wrap)

        self.qty = QSpinBox()
        self.qty.setRange(1, 1_000_000)
        self.qty.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.qty.setMinimumHeight(self._FIELD_H)
        self.unit = QComboBox()
        self.unit.addItem("Piece", "piece")
        self.unit.addItem("Carton", "carton")
        self.unit.setMaximumWidth(120)
        self.unit.currentIndexChanged.connect(self._update_unit_hint)
        self.unit_hint = QLabel("")
        self.unit_hint.setObjectName("Muted")
        qty_row = QHBoxLayout()
        qty_row.addWidget(self.qty, 1)
        qty_row.addWidget(self.unit)
        qty_row.addWidget(self.unit_hint)
        qty_wrap = QWidget(); qty_wrap.setLayout(qty_row)
        entry.addRow("Qty", qty_wrap)

        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 1_000_000_000)
        self.cost.setDecimals(self._decimals)
        self.cost.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.cost.setMinimumHeight(self._FIELD_H)
        self.cost.setGroupSeparatorShown(True)
        self.cost.setPrefix(f"{self._symbol} ")
        entry.addRow("Unit cost/pc", self.cost)

        self.line_disc = QDoubleSpinBox()
        self.line_disc.setRange(0, 1_000_000_000)
        self.line_disc.setDecimals(self._decimals)
        self.line_disc.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.line_disc.setMinimumHeight(self._FIELD_H)
        self.line_disc.setGroupSeparatorShown(True)
        self.line_disc.setPrefix(f"{self._symbol} ")
        disc_row = QHBoxLayout()
        disc_row.addWidget(self.line_disc, 1)
        add_btn = QPushButton("Add item")
        add_btn.clicked.connect(self._add_line)
        disc_row.addWidget(add_btn)
        disc_wrap = QWidget(); disc_wrap.setLayout(disc_row)
        entry.addRow("Disc (line)", disc_wrap)
        root.addLayout(entry)

        # Enter flows through the WHOLE form: Supplier -> Date -> Bill no ->
        # Notes -> Product -> Qty -> Cost -> Disc(adds). Each field is tagged with
        # its chain index on the C++ object, so the handler resolves it even when
        # the key arrives on a spin box's internal editor (whose Python wrapper
        # wouldn't match a dict). Buttons are kept out of Enter so it never opens
        # Browse / Add by accident.
        self._enter_chain = [self.supplier, self.date, self.invoice_no, self.notes,
                             self.prod, self.qty, self.cost, self.line_disc]
        for i, w in enumerate(self._enter_chain):
            w.setProperty("_np_idx", i)
            w.installEventFilter(self)
            inner = w.findChild(QLineEdit)
            if inner is not None and inner is not w:
                inner.installEventFilter(self)
        for b in (browse, add_btn):
            b.setAutoDefault(False); b.setDefault(False)

        # ---- cart ----
        self.table = QTableWidget(0, len(CART_COLS))
        self.table.setHorizontalHeaderLabels(CART_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(5, 40)
        self.table.verticalHeader().setDefaultSectionSize(34)
        # the cart shows a fixed number of rows (see showEvent) and scrolls
        # inside itself when there are more; the rest of the form stays put.
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setMinimumHeight(190)
        self.table.cellClicked.connect(self._on_cart_cell)
        self.table.installEventFilter(self)
        root.addWidget(self.table)

        # ---- totals block (right-aligned) + amount paid ----
        totals = QFormLayout()
        totals.setHorizontalSpacing(16)
        totals.setVerticalSpacing(10)
        totals.setLabelAlignment(Qt.AlignRight)
        self.subtotal_lbl = QLabel(self.controller.fmt(0))
        totals.addRow("Subtotal", self.subtotal_lbl)

        self.bill_disc = QDoubleSpinBox()
        self.bill_disc.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.bill_disc.setMinimumHeight(self._FIELD_H)
        self.bill_disc.setDecimals(self._decimals)
        self.bill_disc.setGroupSeparatorShown(True)
        self.bill_disc.setRange(0, 1_000_000_000)
        self.bill_disc.setPrefix(f"{self._symbol} ")
        self.bill_disc.valueChanged.connect(self._recompute)
        totals.addRow("Bill discount", self.bill_disc)

        self.adv_tax = QDoubleSpinBox()
        self.adv_tax.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.adv_tax.setMinimumHeight(self._FIELD_H)
        self.adv_tax.setDecimals(self._decimals)
        self.adv_tax.setGroupSeparatorShown(True)
        self.adv_tax.setRange(0, 1_000_000_000)
        self.adv_tax.setPrefix(f"{self._symbol} ")
        self.adv_tax.setToolTip("Advance / withholding tax — actual amount, added to the bill.")
        self.adv_tax.valueChanged.connect(self._recompute)
        totals.addRow("Advance tax", self.adv_tax)

        self.total_lbl = QLabel(self.controller.fmt(0))
        self.total_lbl.setStyleSheet("font-size: 18px; font-weight: 700;")
        totals.addRow("Grand total", self.total_lbl)

        self.paid = QDoubleSpinBox()
        self.paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.paid.setMinimumHeight(self._FIELD_H)
        self.paid.setDecimals(self._decimals)
        self.paid.setGroupSeparatorShown(True)
        self.paid.setRange(0, 1_000_000_000)
        self.paid.setPrefix(f"{self._symbol} ")
        self.paid.valueChanged.connect(self._update_credit)
        self.paid.setToolTip("How much you pay the supplier now. 0 = fully on credit.")
        totals.addRow("Amount paid now", self.paid)
        self.credit_lbl = QLabel("")
        self.credit_lbl.setObjectName("Muted")
        totals.addRow("", self.credit_lbl)
        root.addLayout(totals)

        # ---- dialog actions ----
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save purchase")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

        self.prod.setFocus()

    # -- product lookup ----------------------------------------------
    def _refresh_products(self) -> None:
        try:
            rows = self.controller.search_products("", 100000)
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

    def _current_product(self) -> dict | None:
        return self._name_index.get(self.prod.text().strip().lower())

    def _browse_product(self) -> None:
        picker = ProductPickerDialog(self.controller.search_products, self.controller.fmt)
        if picker.exec() and picker.selected:
            self.prod.setText(picker.selected["name"])
            self._on_pick(picker.selected["name"])

    def _on_pick(self, text: str) -> None:
        p = self._name_index.get((text or "").strip().lower())
        if p:
            self.prod.setText(p["name"])
            self._update_unit_hint()
            self.cost.setValue(float(p.get("purchase_price_minor") or 0) / self._minor_units)
            self.line_disc.setValue(0)
            self.qty.setFocus()
            self.qty.selectAll()

    def _pieces(self) -> int:
        entered = int(self.qty.value())
        if self.unit.currentData() == "carton":
            p = self._current_product()
            upc = max(1, int((p or {}).get("units_per_carton") or 1))
            return entered * upc
        return entered

    def _update_unit_hint(self) -> None:
        p = self._current_product()
        upc = int((p or {}).get("units_per_carton") or 1)
        if upc > 1:
            self.unit_hint.setText(f"1 carton = {upc} pcs")
        elif self.unit.currentData() == "carton":
            self.unit_hint.setText("(not sold in cartons)")
        else:
            self.unit_hint.setText("")

    # -- keyboard flow ------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                # resolve which chain field this key belongs to (the event may
                # arrive on a spin box / date edit's inner line editor)
                idx = obj.property("_np_idx") if obj is not None else None
                if idx is None and obj is not None and obj.parent() is not None:
                    idx = obj.parent().property("_np_idx")
                if idx is not None:
                    field = self._enter_chain[idx]
                    if field is self.prod:
                        if self._current_product() is not None:
                            self._on_pick(self.prod.text())
                        return True
                    if field is self.line_disc:
                        self._add_line(); return True
                    nxt = self._enter_chain[idx + 1]
                    nxt.setFocus()
                    if hasattr(nxt, "selectAll"):
                        nxt.selectAll()
                    return True
            if (obj is self.table and key == Qt.Key_Delete):
                self._remove_selected(); return True
        return super().eventFilter(obj, event)

    # -- cart ---------------------------------------------------------
    def _add_line(self) -> None:
        p = self._current_product()
        if p is None:
            QMessageBox.information(self, "Pick a product",
                                   "Choose a product from the list first.")
            self.prod.setFocus()
            return
        qty = self._pieces()
        if qty <= 0:
            QMessageBox.information(self, "Quantity needed", "Enter a quantity.")
            self.qty.setFocus()
            return
        cost_minor = money.to_minor(self.cost.value(), self._minor_units)
        disc_minor = money.to_minor(self.line_disc.value(), self._minor_units)
        gross = qty * cost_minor
        if disc_minor > gross:
            QMessageBox.information(self, "Discount too high",
                                   "The line discount can't exceed the line total.")
            self.line_disc.setFocus()
            return
        # same product already in the cart? bump its quantity
        for ln in self._cart:
            if ln["product_id"] == p["id"] and ln["cost_minor"] == cost_minor \
                    and ln["disc_minor"] == disc_minor:
                ln["qty"] += qty
                break
        else:
            self._cart.append({"product_id": p["id"], "name": p["name"], "qty": qty,
                               "cost_minor": cost_minor, "disc_minor": disc_minor})
        self._render_cart()
        self._recompute()
        # reset entry row, cursor back on Product. The unit (Piece / Carton) is
        # deliberately KEPT so a run of carton items doesn't revert each time;
        # change it only when you want a different unit.
        self.prod.clear()
        self.qty.setValue(1)
        self.unit_hint.clear()
        self.cost.setValue(0)
        self.line_disc.setValue(0)
        self.prod.setFocus()

    def _autosize(self) -> None:
        """The cart height is fixed to _VISIBLE_ROWS (set in showEvent) and scrolls
        internally past that, so nothing to resize here; kept so callers don't need
        to know."""
        return

    def _render_cart(self) -> None:
        self.table.setRowCount(len(self._cart))
        for r, ln in enumerate(self._cart):
            line_total = ln["qty"] * ln["cost_minor"] - ln["disc_minor"]
            cells = [ln["name"], str(ln["qty"]),
                     self.controller.fmt(ln["cost_minor"]),
                     ("− " + self.controller.fmt(ln["disc_minor"])) if ln["disc_minor"] else "—",
                     self.controller.fmt(line_total), "✕"]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c in (1, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 5:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(Qt.red)
                self.table.setItem(r, c, item)
        self._autosize()

    def _on_cart_cell(self, row: int, col: int) -> None:
        if col == len(CART_COLS) - 1 and 0 <= row < len(self._cart):
            self._cart.pop(row)
            self._render_cart()
            self._recompute()

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._cart):
            self._cart.pop(row)
            self._render_cart()
            self._recompute()

    # -- totals -------------------------------------------------------
    def _recompute(self) -> None:
        subtotal = sum(ln["qty"] * ln["cost_minor"] - ln["disc_minor"] for ln in self._cart)
        bill_disc = min(money.to_minor(self.bill_disc.value(), self._minor_units), subtotal)
        tax = money.to_minor(self.adv_tax.value(), self._minor_units)
        grand = subtotal - bill_disc + tax
        self._grand_minor = grand
        self.subtotal_lbl.setText(self.controller.fmt(subtotal))
        self.total_lbl.setText(self.controller.fmt(grand))
        self._update_credit()

    def _update_credit(self) -> None:
        paid_minor = money.to_minor(self.paid.value(), self._minor_units)
        credit = self._grand_minor - paid_minor
        if credit > 0:
            self.credit_lbl.setText("On credit (payable to supplier):  "
                                    + self.controller.fmt(credit))
        elif credit < 0:
            self.credit_lbl.setText("Amount paid exceeds the total.")
        else:
            self.credit_lbl.setText("Paid in full.")

    # -- save ---------------------------------------------------------
    def _save(self) -> None:
        if self.supplier.currentData() is None:
            QMessageBox.warning(self, "Supplier required", "Please select a supplier.")
            return
        if not self._cart:
            QMessageBox.warning(self, "No items", "Add at least one product line.")
            return
        lines = [{"product_id": ln["product_id"], "qty": ln["qty"],
                  "unit_cost": ln["cost_minor"] / self._minor_units,
                  "discount": ln["disc_minor"] / self._minor_units} for ln in self._cart]
        ok, msg, _ = self.controller.create(
            supplier_id=self.supplier.currentData(),
            lines=lines,
            purchase_date=self.date.date().toString("yyyy-MM-dd") + " 00:00:00",
            supplier_invoice_no=self.invoice_no.text().strip() or None,
            notes=self.notes.text().strip() or None,
            amount_paid=self.paid.value(),
            discount=self.bill_disc.value(),
            tax=self.adv_tax.value(),
        )
        if ok:
            QMessageBox.information(self, "Saved", "Purchase recorded and stock updated.")
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)
