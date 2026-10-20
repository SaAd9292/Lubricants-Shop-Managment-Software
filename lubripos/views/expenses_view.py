"""Expenses page.

A fast fixed-entry FORM (same shape as Cash Recovery): pick the category, type
the amount and an optional note, hit Record — the form clears and stays put so
the next expense is one keystroke away. The running list of past expenses lives
behind an "Expense history" button, which opens a filterable, paginated dialog
where rows can be edited or deleted.

Keeping the page itself form-first (instead of table-first) matches how the shop
actually uses it — expenses are entered many times a day, reviewed occasionally.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit,
    QDialog, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.expense_controller import ExpenseController
from ..core.session import current_session
from ..ui.toast import show_toast
from ..ui.widgets import DataTable
from .expense_edit_dialog import ExpenseEditDialog

PAGE_SIZE = 25
COLUMNS = ["Date", "Category", "Amount", "Description", "By"]


class ExpensesView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = ExpenseController(ctx)
        self._minor_units = self.controller.currency()[1]
        self._decimals = max(0, len(str(self._minor_units)) - 1)
        self._build_ui()
        self._load_categories()

    # -- ui -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)

        title_row = QHBoxLayout()
        title = QLabel("Expenses")
        title.setObjectName("PageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.history_btn = QPushButton("Expense history")
        self.history_btn.setObjectName("Secondary")
        self.history_btn.setToolTip("See every expense, filter by date/category, "
                                    "and edit or delete one")
        self.history_btn.clicked.connect(self._open_history)
        title_row.addWidget(self.history_btn)
        root.addLayout(title_row)

        # centre a dialog-style card (same look as Cash Recovery)
        center = QHBoxLayout()
        center.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(540)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(12)

        sub = QLabel("Record a shop expense (rent, electricity, salaries, etc.).")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        cl.addWidget(sub)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        # category + inline "add" (so a new category doesn't need the Settings trip)
        self.category = QComboBox()
        cat_row = QWidget()
        crl = QHBoxLayout(cat_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.addWidget(self.category, 1)
        add_cat = QPushButton("+")
        add_cat.setObjectName("Secondary")
        add_cat.setFixedWidth(36)
        add_cat.setToolTip("Add a new expense category")
        add_cat.clicked.connect(self._add_category)
        crl.addWidget(add_cat)
        form.addRow("Category", cat_row)

        sym, _ = self.controller.currency()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000_000)
        self.amount.setDecimals(self._decimals)
        self.amount.setGroupSeparatorShown(True)
        self.amount.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.amount.setPrefix(f"{sym} ")
        form.addRow("Amount", self.amount)

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        self.date.setDate(QDate.currentDate())
        self.date.setToolTip("Date to record this expense on (back-date if needed)")
        form.addRow("Date", self.date)

        self.description = QLineEdit()
        self.description.setPlaceholderText("Optional note")
        form.addRow("Description", self.description)
        cl.addLayout(form)

        # Enter moves to the NEXT field instead of submitting (fast keyboard
        # entry, like the Back-date form). Only the buttons commit — so neither
        # is a default button (a default button would fire on every Enter).
        #
        # Spin boxes and the date edit deliver key presses to an INTERNAL
        # QLineEdit (and on some platforms that child, not the widget, is what
        # the event filter sees). So we map each field AND its inner line edit to
        # the same slot — otherwise Enter on the Date field would fall through to
        # the widget and pop its calendar instead of advancing.
        self._order = [self.category, self.amount, self.date, self.description]
        self._enter_slot: dict[object, int] = {}
        for i, w in enumerate(self._order):
            w.installEventFilter(self)
            self._enter_slot[w] = i
            inner = w.findChild(QLineEdit)
            if inner is not None and inner is not w:
                inner.installEventFilter(self)
                self._enter_slot[inner] = i

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.again_btn = QPushButton("Save && add another")
        self.again_btn.setObjectName("Secondary")
        self.again_btn.setMinimumHeight(38)
        self.again_btn.setAutoDefault(False)
        self.again_btn.setDefault(False)
        self.again_btn.clicked.connect(lambda: self._record(again=True))
        bar.addWidget(self.again_btn)
        self.record_btn = QPushButton("Record expense")
        self.record_btn.setObjectName("Success")
        self.record_btn.setMinimumHeight(38)
        self.record_btn.setAutoDefault(False)
        self.record_btn.setDefault(False)
        self.record_btn.clicked.connect(lambda: self._record())
        bar.addWidget(self.record_btn)
        cl.addLayout(bar)

        center.addWidget(card)
        center.addStretch(1)
        root.addLayout(center)
        root.addStretch(1)

    # -- nav hook -----------------------------------------------------
    def _reload(self) -> None:
        """Refresh categories whenever the screen is shown (a new one may have
        been added in Settings)."""
        self._load_categories()

    def _load_categories(self) -> None:
        cur = self.category.currentText()
        self.category.clear()
        for c in self.controller.categories():
            self.category.addItem(c["name"], c["name"])
        if cur:
            i = self.category.findText(cur)
            if i >= 0:
                self.category.setCurrentIndex(i)

    def _add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "Add category", "Category name:")
        if ok and name.strip():
            success, msg, _ = self.controller.add_category(name.strip())
            if success:
                self._load_categories()
                self.category.setCurrentText(name.strip())
            else:
                QMessageBox.warning(self, "Error", msg)

    # -- keyboard flow ------------------------------------------------
    def eventFilter(self, obj, event):
        """Enter on any field advances to the next one; Enter on the last field
        (Description) records. Nothing here ever closes the screen."""
        if event.type() == QEvent.KeyPress and event.key() in (
                Qt.Key_Return, Qt.Key_Enter):
            i = self._enter_slot.get(obj)
            if i is not None:
                if i < len(self._order) - 1:
                    self._order[i + 1].setFocus()
                else:
                    self._record(again=True)
                return True        # consume: don't let it trigger anything else
        return super().eventFilter(obj, event)

    # -- record -------------------------------------------------------
    def _record(self, again: bool = False) -> None:
        if not self.category.currentText().strip():
            QMessageBox.information(self, "Pick a category",
                                    "Choose or add a category first.")
            return
        if self.amount.value() <= 0:
            QMessageBox.information(self, "Enter amount",
                                    "Enter an amount greater than zero.")
            return
        form: dict[str, Any] = {
            "expense_date": self.date.date().toString("yyyy-MM-dd") + " 00:00:00",
            "category": self.category.currentText().strip(),
            "amount": self.amount.value(),
            "description": self.description.text().strip(),
        }
        ok, msg, _ = self.controller.save(form)
        if not ok:
            QMessageBox.warning(self, "Could not record", msg)
            return
        show_toast(self, "Expense recorded")
        self.amount.setValue(0)
        self.description.clear()
        # start the next entry at the top of the form (category often changes,
        # e.g. a salary per person); the date is kept as-is for a run of same-day
        # entries.
        self.category.setFocus()

    def _open_history(self) -> None:
        ExpenseHistoryDialog(self.controller, self).exec()


class ExpenseHistoryDialog(QDialog):
    """The full expense list: search + category + date filters, pagination, a
    running filtered total, and inline Edit / Delete per row."""

    def __init__(self, controller: ExpenseController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Expense history")
        # a normal OS window: minimise / maximise / resize, not a fixed modal box
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(760, 420)
        self.resize(900, 580)
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

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search description…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.f_category = QComboBox()
        self._fill_categories()
        self.f_category.currentIndexChanged.connect(self._reset_and_reload)

        self.f_bydate = QCheckBox("By date")
        self.f_bydate.stateChanged.connect(self._on_date_toggle)
        self.f_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.f_to = QDateEdit(QDate.currentDate())
        for de in (self.f_from, self.f_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setEnabled(False)
            de.dateChanged.connect(self._reset_and_reload)

        filters.addWidget(self.search, 1)
        filters.addWidget(self.f_category)
        filters.addWidget(self.f_bydate)
        filters.addWidget(QLabel("From:"))
        filters.addWidget(self.f_from)
        filters.addWidget(QLabel("To:"))
        filters.addWidget(self.f_to)
        root.addLayout(filters)

        self.table = DataTable(0, len(COLUMNS))
        self.table.placeholder = "No expenses match these filters."
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        _hdr = self.table.horizontalHeader()
        _hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._sync_btns)
        self.table.doubleClicked.connect(lambda: self._edit_selected())
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        # row-selection actions (same pattern as Supplier payments) instead of a
        # per-row button column
        self.edit_btn = QPushButton("Edit selected")
        self.edit_btn.setObjectName("Secondary")
        self.edit_btn.setToolTip("Correct the selected expense")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.edit_btn.setEnabled(False)
        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.setObjectName("Secondary")
        self.delete_btn.setToolTip("Delete the selected expense permanently")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.delete_btn.setEnabled(False)
        footer.addWidget(self.edit_btn)
        footer.addWidget(self.delete_btn)
        footer.addSpacing(16)
        self.sum_label = QLabel("")
        self.sum_label.setStyleSheet("font-weight:700;")
        footer.addWidget(self.sum_label)
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

    def _fill_categories(self) -> None:
        self.f_category.clear()
        self.f_category.addItem("All categories", None)
        for c in self.controller.categories():
            self.f_category.addItem(c["name"], c["name"])

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
            category=self.f_category.currentData(),
            date_from=date_from, date_to=date_to,
            limit=PAGE_SIZE, offset=self._page * PAGE_SIZE,
        )
        self._total = result["total"]
        self._populate(result["rows"])
        self.sum_label.setText("Filtered total: "
                               + self.controller.fmt(result["sum_minor"]))
        self._update_pagination()

    def _populate(self, rows: list[dict]) -> None:
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            values = [
                (e.get("expense_date") or "")[:10], e.get("category") or "",
                self.controller.fmt(e["amount_minor"]), e.get("description") or "",
                e.get("created_by_name") or "-",
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, e["id"])
                self.table.setItem(r, c, item)
        self._sync_btns()

    def _sync_btns(self) -> None:
        has = self.table.currentRow() >= 0
        self.edit_btn.setEnabled(has and current_session.can("record.edit"))
        self.delete_btn.setEnabled(has and current_session.can("record.delete"))

    def _update_pagination(self) -> None:
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(
            f"Page {self._page + 1} of {pages}   ({self._total} expenses)")
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

    def _edit_selected(self) -> None:
        eid = self._selected_id()
        if eid is None:
            QMessageBox.information(self, "Select an expense",
                                    "Please select a row first.")
            return
        if not current_session.can("record.edit"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the Edit records privilege.")
            return
        if ExpenseEditDialog(self.controller, expense_id=eid).exec():
            self._reload()

    def _delete_selected(self) -> None:
        eid = self._selected_id()
        if eid is None:
            QMessageBox.information(self, "Select an expense",
                                    "Please select a row first.")
            return
        if not current_session.can("record.delete"):
            QMessageBox.warning(self, "Not allowed",
                                "You do not have the Delete/reverse privilege.")
            return
        confirm = QMessageBox.question(self, "Delete expense",
                                       "Delete this expense permanently?")
        if confirm != QMessageBox.Yes:
            return
        ok, msg, _ = self.controller.delete(eid)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not delete", msg)
