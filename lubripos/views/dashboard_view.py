"""Dashboard: clickable KPI cards + recent sales + low-stock lists."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.money import format_money
from ..services.dashboard_service import DashboardService

ACCENT = "#2563eb"


class _Card(QFrame):
    """A KPI tile. If nav_key + on_click are given, the whole card is clickable."""

    def __init__(self, title: str, nav_key: str | None = None, on_click=None,
                 accent: bool = False) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.nav_key = nav_key
        self.on_click = on_click
        if nav_key and on_click:
            self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(4)
        self._title = QLabel(title)
        self._title.setObjectName("Muted")
        self._value = QLabel("—")
        self._default_color = ACCENT if accent else "palette(text)"
        self._value.setStyleSheet(
            f"font-size: 24px; font-weight: 800; color: {self._default_color};")
        self._hint = QLabel("")
        self._hint.setObjectName("Muted")
        self._hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(self._title)
        lay.addWidget(self._value)
        lay.addWidget(self._hint)

    def set_value(self, text: str, hint: str = "", color: str | None = None) -> None:
        self._value.setText(text)
        self._hint.setText(hint)
        c = color or self._default_color
        self._value.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {c};")

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self.nav_key and self.on_click and e.button() == Qt.LeftButton:
            self.on_click(self.nav_key)
        super().mouseReleaseEvent(e)


class _ListCard(QFrame):
    """A titled card holding a small list of text rows."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(18, 16, 18, 16)
        self._lay.setSpacing(6)
        t = QLabel(title)
        t.setStyleSheet("font-size: 15px; font-weight: 700;")
        self._lay.addWidget(t)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(4)
        self._lay.addLayout(self._rows_box)
        self._lay.addStretch(1)

    def set_rows(self, rows: list[tuple[str, str]], empty_text: str) -> None:
        while self._rows_box.count():
            item = self._rows_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not rows:
            lbl = QLabel(empty_text)
            lbl.setObjectName("Muted")
            self._rows_box.addWidget(lbl)
            return
        for left, right in rows:
            # Wrap each row in a QWidget so set_rows()'s widget-based clear
            # actually deletes it. Adding bare nested layouts leaks the labels
            # (item.widget() is None for a layout), which left stale rows drawn
            # on top of new ones on every refresh.
            rw = QWidget()
            row = QHBoxLayout(rw)
            row.setContentsMargins(0, 0, 0, 0)
            l = QLabel(left)
            r = QLabel(right)
            r.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            r.setStyleSheet("font-weight: 600;")
            row.addWidget(l, 1)
            row.addWidget(r)
            self._rows_box.addWidget(rw)


class _SalesChart(QWidget):
    """Tiny dependency-free bar chart of daily sales (values in minor units)."""

    def __init__(self) -> None:
        super().__init__()
        self._series: list[dict] = []
        self.setMinimumHeight(150)

    def set_series(self, series) -> None:
        self._series = series or []
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        if not self._series:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_t, pad_b = 8, 12, 26
        n = len(self._series)
        maxv = max((x["total"] for x in self._series), default=0) or 1
        avail_w = w - pad_l - 8
        avail_h = h - pad_t - pad_b
        gap = 12
        bar_w = max(6.0, (avail_w - gap * (n - 1)) / n)
        bar_col = QColor(ACCENT)
        label_col = QColor("#6b7280")
        fnt = QFont(); fnt.setPointSize(8); painter.setFont(fnt)
        for i, x in enumerate(self._series):
            bx = pad_l + i * (bar_w + gap)
            bh = (x["total"] / maxv) * avail_h
            painter.fillRect(QRectF(bx, pad_t + (avail_h - bh), bar_w, bh), bar_col)
            painter.setPen(label_col)
            painter.drawText(QRectF(bx - gap / 2, h - pad_b + 3, bar_w + gap, pad_b),
                             Qt.AlignHCenter | Qt.AlignTop, x["label"])
        painter.end()


class DashboardView(QWidget):
    def __init__(self, ctx: AppContext, navigate=None) -> None:
        super().__init__()
        self.ctx = ctx
        self.navigate = navigate
        self.svc = DashboardService(ctx.db)
        self._period = "today"
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(18)

        header = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._period_group = QButtonGroup(self)
        self._period_group.setExclusive(True)
        for _key, _lbl in (("today", "Today"), ("week", "Week"), ("month", "Month")):
            chip = QPushButton(_lbl)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setProperty("period", _key)
            if _key == self._period:
                chip.setChecked(True)
            self._period_group.addButton(chip)
            header.addWidget(chip)
        self._period_group.buttonClicked.connect(self._on_period)
        header.addSpacing(10)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("Secondary")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)

        nav = self.navigate
        grid = QGridLayout()
        grid.setSpacing(16)
        self.card_sales = _Card("Sales", "sales", nav)
        self.card_profit = _Card("Profit", "reports", nav)
        self.card_expenses = _Card("Expenses", "expenses", nav)
        self.card_stock = _Card("Total Stock Value", "products", nav)
        self.card_low = _Card("Low Stock Alerts", "products", nav)
        self.card_products = _Card("Inactive Products", "products", nav)
        cards = [self.card_sales, self.card_profit, self.card_expenses,
                 self.card_stock, self.card_low, self.card_products]
        for i, c in enumerate(cards):
            grid.addWidget(c, i // 3, i % 3)
        root.addLayout(grid)

        chart_card = QFrame()
        chart_card.setObjectName("Card")
        cl = QVBoxLayout(chart_card)
        cl.setContentsMargins(18, 14, 18, 14)
        cl.setSpacing(6)
        ct = QLabel("Sales — last 7 days")
        ct.setStyleSheet("font-size: 15px; font-weight: 700;")
        cl.addWidget(ct)
        self.chart = _SalesChart()
        cl.addWidget(self.chart)
        root.addWidget(chart_card)

        lists = QHBoxLayout()
        lists.setSpacing(16)
        self.recent_card = _ListCard("Recent Sales")
        self.low_card = _ListCard("Low Stock Items")
        lists.addWidget(self.recent_card, 1)
        lists.addWidget(self.low_card, 1)
        root.addLayout(lists, 1)

    def _on_period(self, btn) -> None:
        self._period = btn.property("period")
        self.refresh()

    def refresh(self) -> None:
        c = self.ctx.company.get_company()
        sym = c.get("currency_symbol", "Rs")
        mu = c.get("currency_minor_units", 100)

        def m(v):
            return format_money(v, sym, mu)

        s = self.svc.summary(self._period)
        plabel = {"today": "today", "week": "last 7 days",
                  "month": "this month"}.get(self._period, "today")
        self.card_sales.set_value(m(s["today_sales_minor"]),
                                  f"{s['today_sales_count']} sale(s) {plabel}")
        self.card_profit.set_value(m(s["today_profit_minor"]), f"gross, {plabel}")
        self.card_expenses.set_value(m(s["today_expenses_minor"]), plabel)
        self.card_stock.set_value(m(s["stock_value_minor"]), "at cost")
        low_n = s["low_stock_count"]
        self.card_low.set_value(str(low_n), "at/below minimum",
                                color="#b45309" if low_n else None)
        self.card_products.set_value(str(s["inactive_product_count"]), "inactive")

        sales = self.svc.recent_sales(6)
        self.recent_card.set_rows(
            [(f"{r['invoice_no']}  ·  {(r.get('sale_date') or '')[:16]}", m(r["grand_total_minor"]))
             for r in sales],
            "No sales yet today.")

        low = self.svc.recent_low_stock(6)
        self.low_card.set_rows(
            [(r["name"], f"{r['stock_qty']} / {r['min_stock_level']}") for r in low],
            "Nothing low on stock. ")

        self.chart.set_series(self.svc.sales_series(7))
