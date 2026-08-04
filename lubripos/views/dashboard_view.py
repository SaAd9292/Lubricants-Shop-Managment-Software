"""Dashboard: elevated KPI cards + a polished sales chart + recent/low-stock lists.

Everything is drawn with QPainter (no charting dependency), so it bundles cleanly
into the frozen build. The look: soft-shadowed rounded cards with colour-coded
badges, a gradient bar chart with a currency axis, gridlines, value labels and
hover read-out.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..core.money import format_money
from ..services.dashboard_service import DashboardService

ACCENT = "#2563eb"
_INK = "#0f172a"       # near-black for big values
_MUTE = "#64748b"      # muted label
_FAINT = "#94a3b8"     # fainter hint
_CARD_QSS = "QFrame#DashCard{background:#ffffff;border:1px solid #edf0f3;border-radius:14px;}"


def _short_money(minor: int, mu: int, sym: str) -> str:
    """Abbreviated currency for axis / bar labels: Rs 4k, Rs 17.5k, Rs 1.2M."""
    v = (minor or 0) / mu
    a = abs(v)
    if a >= 1_000_000:
        s = f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    elif a >= 1_000:
        s = f"{v / 1_000:.1f}k".replace(".0k", "k")
    else:
        return f"{sym} {v:,.0f}"
    return f"{sym} {s}"


def _nice_ceil(x: float) -> float:
    """Round up to a clean axis maximum (1, 2, 2.5, 5, 10 × 10ⁿ)."""
    if x <= 0:
        return 1.0
    import math
    mag = 10 ** math.floor(math.log10(x))
    for f in (1, 2, 2.5, 5, 10):
        if x <= f * mag:
            return f * mag
    return 10 * mag


class _Badge(QWidget):
    """A small colour-coded icon chip shown on each KPI card."""

    def __init__(self, kind: str, accent: str) -> None:
        super().__init__()
        self.kind = kind
        self.accent = QColor(accent)
        self.setFixedSize(38, 38)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, 36, 36)
        tint = QColor(self.accent)
        tint.setAlpha(30)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(rect, 11, 11)

        p.setBrush(self.accent)
        p.setPen(QPen(self.accent, 2.0))
        k = self.kind
        if k == "bars":
            p.setPen(Qt.NoPen)
            for i, hh in enumerate((8.0, 12.0, 16.0)):
                p.drawRoundedRect(QRectF(11 + i * 6, 25 - hh, 3.6, hh), 1.6, 1.6)
        elif k == "up":
            p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(19, 12); path.lineTo(26, 23); path.lineTo(12, 23); path.closeSubpath()
            p.drawPath(path)
        elif k == "down":
            p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(12, 15); path.lineTo(26, 15); path.lineTo(19, 26); path.closeSubpath()
            p.drawPath(path)
        elif k == "box":
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(11.5, 11.5, 15, 15), 3.5, 3.5)
            p.drawLine(11.5, 16.5, 26.5, 16.5)
        elif k == "warn":
            p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(19, 11); path.lineTo(27, 26); path.lineTo(11, 26); path.closeSubpath()
            p.drawPath(path)
            p.setPen(QPen(self.accent, 2.0))
            p.drawLine(19, 17, 19, 21.5)
            p.setBrush(self.accent); p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(18.1, 23.0, 1.8, 1.8))
        else:  # "pause" (inactive)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(14, 12, 3.4, 14), 1.5, 1.5)
            p.drawRoundedRect(QRectF(20, 12, 3.4, 14), 1.5, 1.5)
        p.end()


class _UpdateBanner(QFrame):
    """A clickable "software update available" strip shown at the top of the
    dashboard for every user. What the click does is decided by the caller
    (admins are taken to Settings to install; cashiers are told to ask an admin)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("UpdateBanner")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#UpdateBanner{background:#eff6ff;border:1px solid #bfdbfe;"
            "border-radius:12px;}")
        self._cb = None
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)
        pill = QLabel("UPDATE")
        pill.setStyleSheet(
            f"background:{ACCENT};color:#ffffff;border-radius:9px;"
            "padding:3px 9px;font-size:10px;font-weight:800;letter-spacing:1px;")
        self._text = QLabel("")
        self._text.setStyleSheet("color:#1e3a8a;font-size:13px;font-weight:600;")
        chev = QLabel("›")
        chev.setStyleSheet(f"color:{ACCENT};font-size:20px;font-weight:800;")
        h.addWidget(pill, 0, Qt.AlignVCenter)
        h.addWidget(self._text, 1, Qt.AlignVCenter)
        h.addWidget(chev, 0, Qt.AlignVCenter)

    def set(self, text: str, on_click) -> None:
        self._text.setText(text)
        self._cb = on_click

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._cb and e.button() == Qt.LeftButton:
            self._cb()
        super().mouseReleaseEvent(e)


class _Card(QFrame):
    """An elevated KPI tile with a colour accent stripe + badge. Clickable if a
    nav_key + on_click are supplied."""

    def __init__(self, title: str, accent: str = ACCENT, icon: str = "bars",
                 nav_key: str | None = None, on_click=None) -> None:
        super().__init__()
        self.setObjectName("DashCard")
        self.setStyleSheet(_CARD_QSS)
        self.accent = QColor(accent)
        self.nav_key = nav_key
        self.on_click = on_click
        if nav_key and on_click:
            self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(108)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(20)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(5)
        self._shadow.setColor(QColor(15, 23, 42, 34))
        self.setGraphicsEffect(self._shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 15, 16, 15)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self._title = QLabel(title)
        self._title.setStyleSheet(f"color:{_MUTE};font-size:12px;font-weight:600;")
        top.addWidget(self._title, 0, Qt.AlignVCenter)
        top.addStretch(1)
        top.addWidget(_Badge(icon, accent), 0, Qt.AlignTop)
        lay.addLayout(top)

        self._value = QLabel("—")
        vf = QFont(); vf.setPixelSize(27); vf.setWeight(QFont.Bold)
        self._value.setFont(vf)
        self._value.setStyleSheet(f"color:{_INK};")
        lay.addWidget(self._value)
        self._hint = QLabel("")
        self._hint.setStyleSheet(f"color:{_FAINT};font-size:11px;")
        lay.addWidget(self._hint)

    def set_value(self, text: str, hint: str = "", color: str | None = None) -> None:
        self._value.setText(text)
        self._hint.setText(hint)
        self._value.setStyleSheet(f"color:{color or _INK};")

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.accent)
        p.drawRoundedRect(QRectF(1.5, 16, 4.5, self.height() - 32), 2.2, 2.2)
        p.end()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._shadow.setBlurRadius(30)
        self._shadow.setYOffset(9)
        self._shadow.setColor(QColor(15, 23, 42, 60))
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._shadow.setBlurRadius(20)
        self._shadow.setYOffset(5)
        self._shadow.setColor(QColor(15, 23, 42, 34))
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self.nav_key and self.on_click and e.button() == Qt.LeftButton:
            self.on_click(self.nav_key)
        super().mouseReleaseEvent(e)


class _ListCard(QFrame):
    """A titled, shadowed card holding a small list of rows (left text + right
    value). Rows are separated by hairlines for a clean, scannable look."""

    def __init__(self, title: str, accent: str = ACCENT) -> None:
        super().__init__()
        self.setObjectName("DashCard")
        self.setStyleSheet(_CARD_QSS)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20); shadow.setXOffset(0); shadow.setYOffset(5)
        shadow.setColor(QColor(15, 23, 42, 30))
        self.setGraphicsEffect(shadow)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{accent};font-size:11px;")
        t = QLabel(title)
        t.setStyleSheet(f"font-size:15px;font-weight:700;color:{_INK};")
        head.addWidget(dot)
        head.addWidget(t)
        head.addStretch(1)
        self._lay.addLayout(head)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(0)
        self._lay.addLayout(self._rows_box)
        self._lay.addStretch(1)

    def set_rows(self, rows: list, empty_text: str) -> None:
        while self._rows_box.count():
            item = self._rows_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not rows:
            lbl = QLabel(empty_text)
            lbl.setStyleSheet(f"color:{_FAINT};padding-top:6px;")
            self._rows_box.addWidget(lbl)
            return
        for i, row in enumerate(rows):
            left, right = row[0], row[1]
            right_color = row[2] if len(row) > 2 else _INK
            rw = QWidget()
            hb = QHBoxLayout(rw)
            hb.setContentsMargins(0, 8, 0, 8)
            border = "border-top:1px solid #f1f5f9;" if i else ""
            rw.setStyleSheet(f"QWidget{{{border}}}")
            l = QLabel(left)
            l.setStyleSheet("color:#334155;font-size:13px;")
            r = QLabel(right)
            r.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            r.setStyleSheet(f"font-weight:700;color:{right_color};font-size:13px;")
            hb.addWidget(l, 1)
            hb.addWidget(r)
            self._rows_box.addWidget(rw)


class _SalesChart(QWidget):
    """A polished, dependency-free bar chart: gradient rounded bars, a currency
    y-axis with gridlines, per-bar value labels, and a hover read-out."""

    def __init__(self) -> None:
        super().__init__()
        self._series: list[dict] = []
        self._sym = "Rs"
        self._mu = 100
        self._hover = -1
        self._bars: list[QRectF] = []
        self.setMinimumHeight(240)
        self.setMouseTracking(True)

    def set_series(self, series, sym: str = "Rs", mu: int = 100) -> None:
        self._series = series or []
        self._sym = sym
        self._mu = mu
        self._hover = -1
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(56, 20, self.width() - 56 - 14, self.height() - 20 - 28)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        plot = self._plot_rect()
        totals = [x.get("total", 0) for x in self._series]

        if not self._series or max(totals, default=0) == 0:
            p.setPen(QColor(_FAINT))
            f = QFont(); f.setPointSize(10); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "No sales in this period.")
            p.end()
            return

        top = _nice_ceil(max(totals))
        grid_pen = QPen(QColor(0, 0, 0, 16)); grid_pen.setWidthF(1.0)
        lbl_font = QFont(); lbl_font.setPointSize(8)
        p.setFont(lbl_font)
        # gridlines + y-axis labels (0 .. top in 4 steps)
        for i in range(5):
            frac = i / 4
            y = plot.bottom() - frac * plot.height()
            p.setPen(grid_pen)
            p.drawLine(QRectF(plot.left(), y, plot.width(), 0).topLeft(),
                       QRectF(plot.right(), y, 0, 0).topLeft())
            p.setPen(QColor(_FAINT))
            p.drawText(QRectF(0, y - 8, plot.left() - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter,
                       _short_money(int(top * frac), self._mu, self._sym))

        n = len(self._series)
        slot = plot.width() / n
        bar_w = min(46.0, slot * 0.52)
        self._bars = []
        val_font = QFont(); val_font.setPointSize(8); val_font.setBold(True)
        day_font = QFont(); day_font.setPointSize(8)

        for i, x in enumerate(self._series):
            cx = plot.left() + slot * (i + 0.5)
            bx = cx - bar_w / 2
            bh = (x["total"] / top) * plot.height() if top else 0
            by = plot.bottom() - bh
            bar = QRectF(bx, by, bar_w, max(bh, 0.0))
            self._bars.append(QRectF(bx, plot.top(), bar_w, plot.height()))

            hovered = (i == self._hover)
            grad = QLinearGradient(0, by, 0, plot.bottom())
            c_top = QColor(37, 99, 235, 255 if hovered else 235)
            c_bot = QColor(96, 165, 250, 255 if hovered else 205)
            grad.setColorAt(0, c_top)
            grad.setColorAt(1, c_bot)

            if bh > 0.5:
                path = QPainterPath()
                r = min(6.0, bar_w / 2, bh)
                path.moveTo(bar.left(), bar.bottom())
                path.lineTo(bar.left(), bar.top() + r)
                path.quadTo(bar.left(), bar.top(), bar.left() + r, bar.top())
                path.lineTo(bar.right() - r, bar.top())
                path.quadTo(bar.right(), bar.top(), bar.right(), bar.top() + r)
                path.lineTo(bar.right(), bar.bottom())
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.fillPath(path, grad)

            # value label above the bar
            if x["total"] > 0:
                p.setFont(val_font)
                p.setPen(QColor(_INK) if hovered else QColor(_MUTE))
                p.drawText(QRectF(cx - slot / 2, by - 17, slot, 15),
                           Qt.AlignHCenter | Qt.AlignBottom,
                           _short_money(x["total"], self._mu, self._sym))

            # day label
            p.setFont(day_font)
            p.setPen(QColor(_INK) if hovered else QColor(_FAINT))
            p.drawText(QRectF(cx - slot / 2, plot.bottom() + 6, slot, 18),
                       Qt.AlignHCenter | Qt.AlignTop, str(x.get("label", "")))

        # baseline
        p.setPen(QPen(QColor(0, 0, 0, 32), 1.0))
        p.drawLine(plot.bottomLeft(), plot.bottomRight())
        p.end()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        idx = -1
        for i, r in enumerate(self._bars):
            if r.left() <= e.position().x() <= r.right():
                idx = i
                break
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        if self._hover != -1:
            self._hover = -1
            self.update()


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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(28, 26, 28, 28)
        root.setSpacing(20)

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

        # software-update notification (hidden until an update is available)
        self._update_banner = _UpdateBanner()
        self._update_banner.hide()
        root.addWidget(self._update_banner)

        nav = self.navigate
        grid = QGridLayout()
        grid.setSpacing(18)
        # (attr, title, accent, icon, nav_key)
        specs = [
            ("card_sales", "Sales", "#2563eb", "bars", "sales"),
            ("card_profit", "Profit", "#16a34a", "up", "reports"),
            ("card_expenses", "Expenses", "#ef4444", "down", "expenses"),
            ("card_stock", "Total Stock Value", "#7c3aed", "box", "products"),
            ("card_low", "Low Stock Alerts", "#f59e0b", "warn", "products"),
            ("card_products", "Inactive Products", "#64748b", "pause", "products"),
        ]
        for i, (attr, ttl, acc, icon, key) in enumerate(specs):
            card = _Card(ttl, accent=acc, icon=icon, nav_key=key, on_click=nav)
            setattr(self, attr, card)
            grid.addWidget(card, i // 3, i % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        root.addLayout(grid)

        chart_card = QFrame()
        chart_card.setObjectName("DashCard")
        chart_card.setStyleSheet(_CARD_QSS)
        csh = QGraphicsDropShadowEffect(chart_card)
        csh.setBlurRadius(22); csh.setXOffset(0); csh.setYOffset(6)
        csh.setColor(QColor(15, 23, 42, 32))
        chart_card.setGraphicsEffect(csh)
        cl = QVBoxLayout(chart_card)
        cl.setContentsMargins(20, 16, 20, 14)
        cl.setSpacing(2)
        ct = QLabel("Sales — last 7 days")
        ct.setStyleSheet(f"font-size:15px;font-weight:700;color:{_INK};")
        self._chart_sub = QLabel("")
        self._chart_sub.setStyleSheet(f"color:{_FAINT};font-size:11px;")
        cl.addWidget(ct)
        cl.addWidget(self._chart_sub)
        self.chart = _SalesChart()
        cl.addWidget(self.chart, 1)
        root.addWidget(chart_card)

        lists = QHBoxLayout()
        lists.setSpacing(18)
        self.recent_card = _ListCard("Recent Sales", accent="#2563eb")
        self.low_card = _ListCard("Low Stock Items", accent="#f59e0b")
        lists.addWidget(self.recent_card, 1)
        lists.addWidget(self.low_card, 1)
        root.addLayout(lists, 1)

    def set_update_banner(self, text: str, on_click) -> None:
        self._update_banner.set(text, on_click)
        self._update_banner.show()

    def clear_update_banner(self) -> None:
        self._update_banner.hide()

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
        self.card_profit.set_value(m(s["today_profit_minor"]), f"gross, {plabel}",
                                   color="#16a34a")
        self.card_expenses.set_value(m(s["today_expenses_minor"]), plabel,
                                     color="#ef4444" if s["today_expenses_minor"] else None)
        self.card_stock.set_value(m(s["stock_value_minor"]), "at cost")
        low_n = s["low_stock_count"]
        self.card_low.set_value(str(low_n), "at/below minimum",
                                color="#b45309" if low_n else None)
        self.card_products.set_value(str(s["inactive_product_count"]), "inactive")

        sales = self.svc.recent_sales(6)
        self.recent_card.set_rows(
            [(f"{r['invoice_no']}   ·   {(r.get('sale_date') or '')[:16]}",
              m(r["grand_total_minor"])) for r in sales],
            "No sales yet today.")

        low = self.svc.recent_low_stock(6)
        self.low_card.set_rows(
            [(r["name"], f"{r['stock_qty']} / {r['min_stock_level']}", "#dc2626")
             for r in low],
            "Nothing low on stock.")

        series = self.svc.sales_series(7)
        total = sum(x.get("total", 0) for x in series)
        self._chart_sub.setText(f"Daily gross sales  ·  total {m(total)}")
        self.chart.set_series(series, sym, mu)
