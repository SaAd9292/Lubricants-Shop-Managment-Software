"""Purchase return (debit note) dialog.

Return goods to a supplier: pick the supplier, add product lines (qty in pieces
or cartons + the unit cost the goods were bought at), and save. Stock is reduced
and the supplier's payable goes DOWN by the total. No cash moves (it is a debit
note against the account, not a refund).

Admin-only; the Purchases page gates opening it.
"""
from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QCompleter, QDateEdit, QDialog,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..controllers.purchase_controller import PurchaseController
from ..core import money

CART_COLS = ["Product", "Qty", "Unit cost", "Line total", ""]


class PurchaseReturnDialog(QDialog):
    def __init__(self, controller: PurchaseController, supplier_id: int | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._symbol, self._mu = controller.currency()
        self._decimals = max(0, len(str(self._mu or 100)) - 1)
        self._cart: list[dict] = []          # {product_id, name, qty, unit_cost_minor}
        self._name_index: dict[str, dict] = {}
        self.result_data: dict | None = None
        self.setWindowTitle("Return to supplier")
        self.setMinimumWidth(660)
        self._build_ui(supplier_id)
        self._refresh_products()

    # -- ui -----------------------------------------------------------
    def _build_ui(self, supplier_id: int | None) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        hint = QLabel(
            "Return goods to a supplier. Stock is reduced and what you owe the "
            "supplier goes down by the total. No cash changes hands.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # Supplier (required)
        self.supplier = QComboBox()
        self.supplier.addItem("— Select supplier —", None)
        for s in self.controller.active_suppliers():
            self.supplier.addItem(s["name"], s["id"])
            if supplier_id is not None and s["id"] == supplier_id:
                self.supplier.setCurrentIndex(self.supplier.count() - 1)
        form.addRow("Supplier", self.supplier)

        # Product type-ahead
        self.prod = QLineEdit()
        self.prod.setPlaceholderText("Type product name…")
        self._suggest = QCompleter(self)
        self._suggest.setCaseSensitivity(Qt.CaseInsensitive)
        self._suggest.setFilterMode(Qt.MatchContains)
        self._suggest.setCompletionMode(QCompleter.PopupCompletion)
        self.prod.setCompleter(self._suggest)
        self._suggest.activated[str].connect(self._on_pick)
        self.prod.installEventFilter(self)
        form.addRow("Product", self.prod)

        # Qty + unit (Piece / Carton)
        self.qty = QSpinBox()
        self.qty.setRange(1, 1_000_000)
        self.qty.setButtonSymbols(QAbstractSpinBox.NoButtons)
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
        form.addRow("Qty", qty_wrap)

        # Unit cost (per piece) — defaults to the product's purchase price
        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 1_000_000_000)
        self.cost.setDecimals(self._decimals)
        self.cost.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.cost.setGroupSeparatorShown(True)
        self.cost.setPrefix(f"{self._symbol} ")
        add_row = QHBoxLayout()
        add_row.addWidget(self.cost, 1)
        add_btn = QPushButton("Add item")
        add_btn.clicked.connect(self._add_line)
        add_row.addWidget(add_btn)
        add_wrap = QWidget(); add_wrap.setLayout(add_row)
        form.addRow("Unit cost/pc", add_wrap)
        root.addLayout(form)

        # cart
        self.cart = QTableWidget(0, len(CART_COLS))
        self.cart.setHorizontalHeaderLabels(CART_COLS)
        self.cart.verticalHeader().setVisible(False)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cart.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cart.setColumnWidth(4, 40)
        self.cart.cellClicked.connect(self._on_cell)
        root.addWidget(self.cart, 1)

        # date + notes
        meta = QFormLayout()
        meta.setHorizontalSpacing(16)
        self.ret_date = QDateEdit()
        self.ret_date.setCalendarPopup(True)
        self.ret_date.setDisplayFormat("dd MMM yyyy")
        self.ret_date.setMaximumDate(QDate.currentDate())
        self.ret_date.setDate(QDate.currentDate())
        meta.addRow("Return date", self.ret_date)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Reason / note (optional)")
        meta.addRow("Note", self.notes)
        root.addLayout(meta)

        foot = QHBoxLayout()
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet("font-weight:700; font-size:15px;")
        foot.addWidget(self.total_lbl)
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.ok_btn = QPushButton("Record return")
        self.ok_btn.setObjectName("Success")
        self.ok_btn.setMinimumHeight(36)
        self.ok_btn.clicked.connect(self._process)
        self.ok_btn.setEnabled(False)
        foot.addWidget(self.ok_btn)
        root.addLayout(foot)

        self._update_total()
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

    def _on_pick(self, text: str) -> None:
        p = self._name_index.get((text or "").strip().lower())
        if p:
            self._update_unit_hint()
            self.cost.setValue(float(p.get("purchase_price_minor") or 0) / (self._mu or 100))
            self.qty.setFocus()
            self.qty.selectAll()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if (obj is self.prod and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            if self._current_product() is not None:
                self._on_pick(self.prod.text())
                return True
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
            QMessageBox.information(self, "Quantity needed",
                                    "Enter how many are being returned.")
            self.qty.setFocus()
            return
        unit_minor = money.to_minor(self.cost.value(), self._mu)
        self._cart.append({"product_id": p["id"], "name": p["name"],
                           "qty": qty, "unit_cost_minor": unit_minor})
        self._render_cart()
        self._update_total()
        self.prod.clear()
        self.qty.setValue(1)
        self.unit.setCurrentIndex(0)
        self.unit_hint.clear()
        self.cost.setValue(0)
        self.prod.setFocus()

    def _render_cart(self) -> None:
        self.cart.setRowCount(len(self._cart))
        for r, ln in enumerate(self._cart):
            line_total = ln["qty"] * ln["unit_cost_minor"]
            cells = [ln["name"], str(ln["qty"]),
                     self.controller.fmt(ln["unit_cost_minor"]),
                     self.controller.fmt(line_total), "✕"]
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
            self._update_total()

    def _total_minor(self) -> int:
        return sum(ln["qty"] * ln["unit_cost_minor"] for ln in self._cart)

    def _update_total(self) -> None:
        self.total_lbl.setText("Return total:  " + self.controller.fmt(self._total_minor()))
        self.ok_btn.setEnabled(bool(self._cart))

    # -- process ------------------------------------------------------
    def _process(self) -> None:
        if not self._cart:
            return
        supplier_id = self.supplier.currentData()
        if supplier_id is None:
            QMessageBox.information(self, "Supplier required",
                                    "Choose the supplier you are returning to.")
            return
        total = self._total_minor()
        confirm = QMessageBox.question(
            self, "Confirm return",
            f"Return {len(self._cart)} line(s) to {self.supplier.currentText()}?\n\n"
            f"Stock will be reduced and what you owe them will drop by "
            f"{self.controller.fmt(total)}. No cash moves.")
        if confirm != QMessageBox.Yes:
            return
        lines = [{"product_id": ln["product_id"], "qty": ln["qty"],
                  "unit_cost": ln["unit_cost_minor"] / (self._mu or 100)}
                 for ln in self._cart]
        ok, msg, data = self.controller.create_return(
            supplier_id=supplier_id, lines=lines,
            return_date=self.ret_date.date().toString("yyyy-MM-dd") + " 12:00:00",
            notes=self.notes.text().strip() or None)
        if ok:
            self.result_data = data
            QMessageBox.information(
                self, "Return recorded",
                f"Stock reduced and {self.controller.fmt(data['total_minor'])} "
                "taken off the supplier balance.")
            self.accept()
        else:
            QMessageBox.warning(self, "Could not record return", msg)
