"""Customers page: directory of customers with per-customer purchase history
("which oil did they buy last time?"). Searchable, sortable, paginated.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.customer_controller import CustomerController
from ..ui.widgets import DataTable

PAGE_SIZE = 25
# label, sort key, right-aligned?
COLUMNS = [("Name", "name", False), ("Phone", None, False),
           ("Sales", "sales_count", True), ("Last purchase", "last_purchase", False),
           ("Total spent", "total_spent", True)]


def _money_item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class CustomersView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = CustomerController(ctx)
        self._page = 0
        self._total = 0
        self._sort_by = "name"
        self._sort_dir = "asc"
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reload)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Customers")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add Customer")
        add_btn.clicked.connect(self._add)
        header.addWidget(add_btn)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or phone…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_inactive = QCheckBox("Show inactive")
        self.f_inactive.stateChanged.connect(self._reset_and_reload)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_inactive)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = ("No customers yet. They're added automatically "
                                  "when you attach one to a sale, or click "
                                  '"+ Add Customer".')
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._on_sort)
        self.table.doubleClicked.connect(lambda: self._open_history())
        root.addWidget(self.table, 1)

        hint = QLabel("Double-click a customer to see their purchase history.")
        hint.setObjectName("Muted")
        root.addWidget(hint)

        footer = QHBoxLayout()
        hist_btn = QPushButton("View history")
        hist_btn.setObjectName("Secondary")
        hist_btn.clicked.connect(self._open_history)
        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("Secondary")
        edit_btn.clicked.connect(self._edit_selected)
        self.del_btn = QPushButton("Remove")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.clicked.connect(self._delete_selected)
        footer.addWidget(hist_btn)
        footer.addWidget(edit_btn)
        footer.addWidget(self.del_btn)
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
    def _reset_and_reload(self) -> None:
        self._page = 0
        self._reload()

    def _reload(self) -> None:
        res = self.controller.list(
            search=self.search.text(), only_active=not self.f_inactive.isChecked(),
            sort_by=self._sort_by, sort_dir=self._sort_dir,
            limit=PAGE_SIZE, offset=self._page * PAGE_SIZE)
        self._total = res["total"]
        self._populate(res["rows"])
        self._update_pagination()

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            name = QTableWidgetItem(c["name"] + ("" if c["is_active"] else "  (inactive)"))
            name.setData(Qt.UserRole, c["id"])
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(c.get("phone") or ""))
            n = _money_item(str(c.get("sales_count", 0)))
            self.table.setItem(r, 2, n)
            last = (c.get("last_purchase") or "")[:16]
            self.table.setItem(r, 3, QTableWidgetItem(last or "—"))
            self.table.setItem(r, 4, _money_item(self.controller.fmt(c.get("total_spent", 0))))

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"Page {self._page + 1} of {pages}   ({self._total} customers)")
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

    def _on_sort(self, col: int) -> None:
        key = COLUMNS[col][1]
        if not key:
            return
        if self._sort_by == key:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_by, self._sort_dir = key, "asc"
        self._page = 0
        self._reload()

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    # -- actions ------------------------------------------------------
    def _add(self) -> None:
        if CustomerEditDialog(self.controller).exec():
            self._reset_and_reload()

    def _edit_selected(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Select a customer", "Please select a row first.")
            return
        if CustomerEditDialog(self.controller, customer_id=cid).exec():
            self._reload()

    def _open_history(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Select a customer", "Please select a row first.")
            return
        CustomerHistoryDialog(self, self.controller, cid).exec()

    def _delete_selected(self) -> None:
        cid = self._selected_id()
        if cid is None:
            QMessageBox.information(self, "Select a customer", "Please select a row first.")
            return
        if self.f_inactive.isChecked():
            ok, msg, _ = self.controller.reactivate(cid)
        else:
            if QMessageBox.question(self, "Remove customer",
                                    "Remove this customer? Their past sales are kept."
                                    ) != QMessageBox.Yes:
                return
            ok, msg, _ = self.controller.remove(cid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Action failed", msg)


class CustomerEditDialog(QDialog):
    def __init__(self, controller: CustomerController, customer_id: int | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.customer_id = customer_id
        self.setWindowTitle("Edit Customer" if customer_id else "Add Customer")
        self.setMinimumWidth(340)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.notes = QLineEdit()
        form.addRow("Name", self.name)
        form.addRow("Phone", self.phone)
        form.addRow("Notes", self.notes)
        if customer_id is not None:
            c = controller.get(customer_id)
            self.name.setText(c.get("name") or "")
            self.phone.setText(c.get("phone") or "")
            self.notes.setText(c.get("notes") or "")
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setObjectName("Success")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _save(self) -> None:
        form = {"name": self.name.text().strip(), "phone": self.phone.text().strip(),
                "notes": self.notes.text().strip()}
        if not form["name"]:
            QMessageBox.information(self, "Name required", "Enter a customer name.")
            return
        ok, msg, _ = self.controller.save(form, self.customer_id)
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, "Could not save", msg)


class CustomerHistoryDialog(QDialog):
    def __init__(self, parent, controller: CustomerController, customer_id: int) -> None:
        super().__init__(parent)
        self.controller = controller
        data = controller.history(customer_id)
        cust = data["customer"]
        self.setWindowTitle(f"History — {cust['name']}")
        self.resize(700, 540)
        root = QVBoxLayout(self)

        head = QLabel(f"{cust['name']}"
                      + (f"   ·   {cust['phone']}" if cust.get("phone") else "")
                      + f"      Visits: {data['visits']}      "
                      f"Total spent: {controller.fmt(data['total_spent'])}")
        head.setObjectName("PageTitle")
        root.addWidget(head)

        root.addWidget(QLabel("Products bought"))
        pcols = ["Product", "Total qty", "Visits", "Last price", "Last bought"]
        ptbl = DataTable(0, len(pcols))
        ptbl.placeholder = "No purchases on record."
        ptbl.setHorizontalHeaderLabels(pcols)
        ptbl.verticalHeader().setVisible(False)
        ptbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ptbl.setRowCount(len(data["products"]))
        for r, p in enumerate(data["products"]):
            ptbl.setItem(r, 0, QTableWidgetItem(p["product"]))
            ptbl.setItem(r, 1, _money_item(str(p["qty"])))
            ptbl.setItem(r, 2, _money_item(str(p["visits"])))
            ptbl.setItem(r, 3, _money_item(controller.fmt(p["last_price"] or 0)))
            ptbl.setItem(r, 4, QTableWidgetItem((p["last_date"] or "")[:16]))
        ptbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        root.addWidget(ptbl, 1)

        root.addWidget(QLabel("Sales"))
        scols = ["Invoice", "Date", "Items", "Total"]
        stbl = DataTable(0, len(scols))
        stbl.placeholder = "No sales on record."
        stbl.setHorizontalHeaderLabels(scols)
        stbl.verticalHeader().setVisible(False)
        stbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        stbl.setRowCount(len(data["sales"]))
        for r, sr in enumerate(data["sales"]):
            stbl.setItem(r, 0, QTableWidgetItem(sr["invoice"]))
            stbl.setItem(r, 1, QTableWidgetItem(sr["date"]))
            stbl.setItem(r, 2, _money_item(str(sr["items"])))
            stbl.setItem(r, 3, _money_item(controller.fmt(sr["total"])))
        stbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(stbl, 1)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addWidget(box)
