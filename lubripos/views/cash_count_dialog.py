"""End-of-day cash count (drawer reconciliation).

A blind count: the cashier counts the physical cash and types the total, then
presses Check to reveal what the system EXPECTED (the running Cash in Hand) and
the difference (over / short / balanced). Saving records the count for the audit
trail. It never adjusts Cash in Hand — a real shortage stays visible.
"""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ..app_context import AppContext
from ..controllers.cash_controller import CashController
from ..core import money
from ..ui.toast import show_toast


class CashCountDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.controller = CashController(ctx)
        self._checked = False
        self.setWindowTitle("End-of-day cash count")
        self.setMinimumWidth(460)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        intro = QLabel("Pick the day, count the cash that came into the drawer, "
                       "and press Check to compare it against that day's takings.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        root.addWidget(intro)

        last = self.controller.last_count()
        if last:
            diff = last["difference_minor"]
            word = "balanced" if diff == 0 else ("over" if diff > 0 else "short")
            when = last.get("count_date") or (last.get("counted_at") or "")[:10]
            self._last_lbl = QLabel(
                f"Last count: {when}  ·  "
                f"{word}" + ("" if diff == 0 else f" by {self.controller.fmt(abs(diff))}"))
            self._last_lbl.setObjectName("Muted")
            root.addWidget(self._last_lbl)

        sym, _ = self.controller.currency()
        form = QFormLayout()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMaximumDate(QDate.currentDate())
        self.date.setDate(QDate.currentDate())
        self.date.dateChanged.connect(self._on_amount_changed)   # invalidate preview
        form.addRow("Day", self.date)
        self.amount = QDoubleSpinBox()
        self.amount.setMaximum(999_999_999)
        self.amount.setDecimals(2)
        self.amount.setPrefix(f"{sym} ")
        self.amount.valueChanged.connect(self._on_amount_changed)
        form.addRow("Counted cash", self.amount)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Reason / note (optional)")
        form.addRow("Note", self.note)
        root.addLayout(form)

        # result panel (hidden until Check)
        self.result = QFrame()
        self.result.setObjectName("Card")
        rl = QVBoxLayout(self.result)
        rl.setContentsMargins(16, 12, 16, 12)
        rl.setSpacing(4)
        self.exp_lbl = QLabel("")
        self.cnt_lbl = QLabel("")
        self.diff_lbl = QLabel("")
        self.diff_lbl.setStyleSheet("font-size:16px; font-weight:700;")
        for w in (self.exp_lbl, self.cnt_lbl):
            w.setStyleSheet("font-size:13px;")
        rl.addWidget(self.exp_lbl)
        rl.addWidget(self.cnt_lbl)
        rl.addWidget(self.diff_lbl)
        self.result.hide()
        root.addWidget(self.result)

        bar = QHBoxLayout()
        self.check_btn = QPushButton("Check")
        self.check_btn.setObjectName("Secondary")
        self.check_btn.clicked.connect(self._check)
        bar.addWidget(self.check_btn)
        bar.addStretch(1)
        cancel = QPushButton("Close")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        self.save_btn = QPushButton("Save count")
        self.save_btn.setObjectName("Success")
        self.save_btn.setMinimumHeight(36)
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

    def _on_amount_changed(self, _v=None) -> None:
        # editing the count after a check invalidates the preview
        if self._checked:
            self._checked = False
            self.result.hide()
            self.save_btn.setEnabled(False)

    def _day(self) -> str:
        return self.date.date().toString("yyyy-MM-dd")

    def _check(self) -> None:
        fmt = self.controller.fmt
        expected = self.controller.expected_cash(self._day())
        _, mu = self.controller.currency()
        counted = money.to_minor(self.amount.value(), mu)
        diff = counted - expected
        self.exp_lbl.setText(f"Expected (that day's cash takings):  {fmt(expected)}")
        self.cnt_lbl.setText(f"Counted (actual):  {fmt(counted)}")
        if diff == 0:
            self.diff_lbl.setText("Balanced — no difference")
            self.diff_lbl.setStyleSheet("font-size:16px; font-weight:700; color:#16a34a;")
        else:
            word = "OVER" if diff > 0 else "SHORT"
            color = "#b45309" if diff > 0 else "#dc2626"
            self.diff_lbl.setText(f"{word} by {fmt(abs(diff))}")
            self.diff_lbl.setStyleSheet(
                f"font-size:16px; font-weight:700; color:{color};")
        self.result.show()
        self._checked = True
        self.save_btn.setEnabled(True)

    def _save(self) -> None:
        if not self._checked:
            self._check()
        ok, msg, data = self.controller.record_count(
            self.amount.value(), day=self._day(), notes=self.note.text())
        if not ok:
            QMessageBox.warning(self, "Could not save count", msg)
            return
        show_toast(self, "Cash count saved")
        self.accept()
