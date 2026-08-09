"""Cash Drawer (till) screen.

Open the drawer with a starting float, log cash taken out/in during the day,
then close it by counting the cash — the app shows expected-vs-counted and the
variance so shortages are obvious. A history of closed sessions sits below.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..controllers.cash_drawer_controller import CashDrawerController

_INK = "#0f172a"
_MUTE = "#64748b"
_GREEN = "#16a34a"
_RED = "#dc2626"


def _money_spin(decimals: int) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setMaximum(99_999_999)
    s.setDecimals(decimals)
    s.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return s


class CashDrawerView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = CashDrawerController(ctx)
        self._sym, self._mu = self.controller.currency()
        self._decimals = max(0, len(str(self._mu)) - 1)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(28, 26, 28, 28)
        root.setSpacing(16)

        title = QLabel("Cash Drawer")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        # -- OPEN panel (shown when no drawer is open) --
        self.open_panel = QFrame()
        self.open_panel.setObjectName("Card")
        op = QVBoxLayout(self.open_panel)
        op.setContentsMargins(18, 16, 18, 16)
        op.addWidget(QLabel("No cash drawer is open. Start the day by entering the "
                            "cash already in the till:"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Opening float:"))
        self.float_spin = _money_spin(self._decimals)
        row.addWidget(self.float_spin)
        open_btn = QPushButton("Open drawer")
        open_btn.setObjectName("Success")
        open_btn.clicked.connect(self._open_drawer)
        row.addWidget(open_btn)
        row.addStretch(1)
        op.addLayout(row)
        root.addWidget(self.open_panel)

        # -- SESSION panel (shown when a drawer is open) --
        self.session_panel = QFrame()
        self.session_panel.setObjectName("Card")
        sp = QVBoxLayout(self.session_panel)
        sp.setContentsMargins(18, 16, 18, 16)
        sp.setSpacing(10)
        self.session_head = QLabel("")
        self.session_head.setStyleSheet(f"font-weight:700;font-size:14px;color:{_INK};")
        sp.addWidget(self.session_head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(4)
        self._rows = {}
        specs = [("opening", "Opening float", _INK), ("cash_sales", "Cash sales", _GREEN),
                 ("cash_repay", "Debt repayments (cash)", _GREEN), ("paid_in", "Cash in", _GREEN),
                 ("cash_refunds", "Refunds", _RED), ("cash_expenses", "Cash expenses", _RED),
                 ("paid_out", "Cash out (paid)", _RED)]
        for i, (key, label, color) in enumerate(specs):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{_MUTE};")
            val = QLabel("—")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setStyleSheet(f"font-weight:600;color:{color};")
            self.grid.addWidget(lbl, i, 0)
            self.grid.addWidget(val, i, 1)
            self._rows[key] = val
        exp_lbl = QLabel("Expected cash in drawer")
        exp_lbl.setStyleSheet(f"font-weight:700;color:{_INK};")
        self.exp_val = QLabel("—")
        self.exp_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.exp_val.setStyleSheet(f"font-weight:800;font-size:15px;color:{_INK};")
        self.grid.addWidget(exp_lbl, len(specs), 0)
        self.grid.addWidget(self.exp_val, len(specs), 1)
        self.grid.setColumnStretch(1, 1)
        sp.addLayout(self.grid)

        actions = QHBoxLayout()
        out_btn = QPushButton("Cash out")
        out_btn.setObjectName("Secondary")
        out_btn.clicked.connect(lambda: self._movement("out"))
        in_btn = QPushButton("Cash in")
        in_btn.setObjectName("Secondary")
        in_btn.clicked.connect(lambda: self._movement("in"))
        close_btn = QPushButton("Close drawer")
        close_btn.setObjectName("Success")
        close_btn.clicked.connect(self._close_drawer)
        actions.addWidget(out_btn)
        actions.addWidget(in_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        sp.addLayout(actions)

        sp.addWidget(QLabel("Cash movements this session"))
        self.moves = QTableWidget(0, 4)
        self.moves.setHorizontalHeaderLabels(["Time", "Type", "Amount", "Reason"])
        self.moves.verticalHeader().setVisible(False)
        self.moves.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.moves.setMinimumHeight(120)
        self.moves.horizontalHeader().setStretchLastSection(True)
        sp.addWidget(self.moves)
        root.addWidget(self.session_panel)

        # -- history of closed sessions --
        root.addWidget(QLabel("Recent sessions"))
        self.history = QTableWidget(0, 7)
        self.history.setHorizontalHeaderLabels(
            ["Opened", "Closed", "By", "Opening", "Expected", "Counted", "Variance"])
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.history, 1)

    # -- data ---------------------------------------------------------
    def refresh(self) -> None:
        fmt = self.controller.fmt
        session = self.controller.current()
        self.open_panel.setVisible(session is None)
        self.session_panel.setVisible(session is not None)
        if session:
            self.session_head.setText(
                f"Drawer OPEN · started {(session.get('opened_at') or '')[:16]}"
                + (f" by {session.get('opened_by_name')}" if session.get("opened_by_name") else ""))
            t = self.controller.totals(session)
            for key, lbl in self._rows.items():
                sign = "-" if key in ("cash_refunds", "cash_expenses", "paid_out") else ""
                lbl.setText(sign + fmt(t[key]))
            self.exp_val.setText(fmt(t["expected"]))
            self._fill_moves(self.controller.movements(session["id"]))
        self._fill_history(self.controller.list_sessions(30))

    def _fill_moves(self, rows) -> None:
        self.moves.setRowCount(len(rows))
        for r, m in enumerate(rows):
            self.moves.setItem(r, 0, QTableWidgetItem(m["at"]))
            self.moves.setItem(r, 1, QTableWidgetItem("Cash out" if m["kind"] == "out" else "Cash in"))
            amt = QTableWidgetItem(("-" if m["kind"] == "out" else "+") + self.controller.fmt(m["amount_minor"]))
            amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.moves.setItem(r, 2, amt)
            self.moves.setItem(r, 3, QTableWidgetItem(m["reason"]))

    def _fill_history(self, rows) -> None:
        fmt = self.controller.fmt
        self.history.setRowCount(len(rows))
        for r, s in enumerate(rows):
            closed = s.get("status") == "closed"
            cells = [
                (s.get("opened_at") or "")[:16],
                (s.get("closed_at") or "")[:16] if closed else "OPEN",
                s.get("opened_by_name") or "-",
                fmt(s.get("opening_float_minor") or 0),
                fmt(s["expected_cash_minor"]) if closed and s.get("expected_cash_minor") is not None else "-",
                fmt(s["counted_cash_minor"]) if closed and s.get("counted_cash_minor") is not None else "-",
            ]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c in (3, 4, 5):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.history.setItem(r, c, it)
            var = s.get("variance_minor")
            vtext = fmt(var) if (closed and var is not None) else "-"
            vit = QTableWidgetItem(vtext)
            vit.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if closed and var is not None and var != 0:
                from PySide6.QtGui import QColor
                vit.setForeground(QColor(_RED if var < 0 else _GREEN))
            self.history.setItem(r, 6, vit)

    # -- actions ------------------------------------------------------
    def _open_drawer(self) -> None:
        ok, msg, _ = self.controller.open(self.float_spin.value())
        if ok:
            self.float_spin.setValue(0)
            self.refresh()
        else:
            QMessageBox.warning(self, "Could not open drawer", msg)

    def _movement(self, kind: str) -> None:
        session = self.controller.current()
        if not session:
            return
        dlg = _MovementDialog(self, kind, self._decimals)
        if dlg.exec() != QDialog.Accepted:
            return
        amount, reason = dlg.values()
        if amount <= 0:
            QMessageBox.information(self, "Enter amount", "Enter an amount greater than zero.")
            return
        ok, msg, _ = self.controller.add_movement(session["id"], kind, amount, reason)
        if ok:
            self.refresh()
        else:
            QMessageBox.warning(self, "Could not record", msg)

    def _close_drawer(self) -> None:
        session = self.controller.current()
        if not session:
            return
        expected = self.controller.totals(session)["expected"]
        dlg = _CloseDialog(self, expected, self.controller.fmt, self._mu, self._decimals)
        if dlg.exec() != QDialog.Accepted:
            return
        counted, note = dlg.values()
        ok, msg, data = self.controller.close(session["id"], counted, note)
        if not ok:
            QMessageBox.warning(self, "Could not close drawer", msg)
            return
        var = data["variance_minor"]
        state = "matches exactly" if var == 0 else \
            (f"is OVER by {self.controller.fmt(abs(var))}" if var > 0
             else f"is SHORT by {self.controller.fmt(abs(var))}")
        QMessageBox.information(
            self, "Drawer closed",
            f"Expected: {self.controller.fmt(data['expected_cash_minor'])}\n"
            f"Counted:  {self.controller.fmt(data['counted_cash_minor'])}\n\n"
            f"The till {state}.")
        self.refresh()


_DIALOG_QSS = """
QDialog { background:#ffffff; }
QLabel#DlgTitle { font-size:16px; font-weight:700; color:#0f172a; }
QLabel#DlgSub { color:#94a3b8; font-size:12px; }
QLabel#DlgField { color:#475569; font-size:12px; font-weight:600; }
QLineEdit, QDoubleSpinBox {
    background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;
    padding:0 10px; min-height:34px; font-size:13px; color:#0f172a;
}
QLineEdit:focus, QDoubleSpinBox:focus { border:1px solid #2563eb; background:#ffffff; }
QFrame#DlgBox { background:#f8fafc; border:1px solid #edf0f3; border-radius:10px; }
QPushButton#DlgPrimary {
    background:#2563eb; color:#ffffff; border:none; border-radius:8px;
    padding:0 20px; font-size:13px; font-weight:600;
}
QPushButton#DlgPrimary:hover { background:#1d4ed8; }
QPushButton#DlgPrimary:pressed { background:#1e40af; }
QPushButton#DlgGhost {
    background:#ffffff; color:#475569; border:1px solid #e2e8f0;
    border-radius:8px; padding:0 18px; font-size:13px; font-weight:600;
}
QPushButton#DlgGhost:hover { background:#f1f5f9; }
"""


def _field(label: str, widget) -> QVBoxLayout:
    v = QVBoxLayout()
    v.setSpacing(4)
    lbl = QLabel(label)
    lbl.setObjectName("DlgField")
    v.addWidget(lbl)
    v.addWidget(widget)
    return v


class _MovementDialog(QDialog):
    def __init__(self, parent, kind: str, decimals: int) -> None:
        super().__init__(parent)
        out = kind == "out"
        self.setWindowTitle("Cash out" if out else "Cash in")
        self.setFixedWidth(400)
        self.setStyleSheet(_DIALOG_QSS)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(4)
        title = QLabel("Cash taken out" if out else "Cash added in")
        title.setObjectName("DlgTitle")
        sub = QLabel("Money removed from the till (e.g. a bank deposit)." if out
                     else "Money put into the till (e.g. adding change).")
        sub.setObjectName("DlgSub")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(14)
        self.amount = _money_spin(decimals)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("e.g. chai, bank deposit")
        root.addLayout(_field("Amount", self.amount))
        root.addSpacing(10)
        root.addLayout(_field("Reason", self.reason))
        root.addSpacing(18)
        bar = QHBoxLayout()
        bar.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("DlgGhost")
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.reject)
        okb = QPushButton("Record")
        okb.setObjectName("DlgPrimary")
        okb.setMinimumHeight(38)
        okb.setDefault(True)
        okb.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(okb)
        root.addLayout(bar)

    def values(self):
        return self.amount.value(), self.reason.text().strip()


class _CloseDialog(QDialog):
    def __init__(self, parent, expected_minor: int, fmt, mu: int, decimals: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Close cash drawer")
        self.setFixedWidth(400)
        self.setStyleSheet(_DIALOG_QSS)
        self._expected = expected_minor
        self._mu = mu
        self._fmt = fmt

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(4)
        title = QLabel("Close cash drawer")
        title.setObjectName("DlgTitle")
        sub = QLabel("Count the cash physically in the till and enter it below.")
        sub.setObjectName("DlgSub")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(14)

        # expected-cash highlight box
        box = QFrame()
        box.setObjectName("DlgBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(14, 12, 14, 12)
        el = QLabel("Expected cash in drawer")
        el.setStyleSheet("color:#475569;font-weight:600;")
        ev = QLabel(fmt(expected_minor))
        ev.setStyleSheet("color:#0f172a;font-weight:800;font-size:15px;")
        ev.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bl.addWidget(el)
        bl.addWidget(ev, 1)
        root.addWidget(box)
        root.addSpacing(14)

        self.counted = _money_spin(decimals)
        self.counted.valueChanged.connect(self._update_var)
        root.addLayout(_field("Counted cash", self.counted))
        root.addSpacing(6)

        var_row = QHBoxLayout()
        vlab = QLabel("Variance")
        vlab.setObjectName("DlgField")
        self.var_lbl = QLabel("—")
        self.var_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.var_lbl.setStyleSheet("font-weight:700;")
        var_row.addWidget(vlab)
        var_row.addWidget(self.var_lbl, 1)
        root.addLayout(var_row)
        root.addSpacing(10)

        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional note (e.g. reason for a shortage)")
        root.addLayout(_field("Note", self.note))
        root.addSpacing(18)

        bar = QHBoxLayout()
        bar.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("DlgGhost")
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.reject)
        okb = QPushButton("Close drawer")
        okb.setObjectName("DlgPrimary")
        okb.setMinimumHeight(38)
        okb.setDefault(True)
        okb.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(okb)
        root.addLayout(bar)
        self._update_var()

    def _update_var(self) -> None:
        counted_minor = int(round(self.counted.value() * self._mu))
        var = counted_minor - self._expected
        self.var_lbl.setText(self._fmt(var))
        self.var_lbl.setStyleSheet(
            "font-weight:700;color:%s;" % (_INK if var == 0 else (_GREEN if var > 0 else _RED)))

    def values(self):
        return self.counted.value(), self.note.text().strip()
