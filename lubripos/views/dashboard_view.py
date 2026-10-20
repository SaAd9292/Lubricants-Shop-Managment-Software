"""Dashboard: elevated KPI cards + a polished sales chart + recent/low-stock lists.

Everything is drawn with QPainter (no charting dependency), so it bundles cleanly
into the frozen build. The look: soft-shadowed rounded cards with colour-coded
badges, a gradient bar chart with a currency axis, gridlines, value labels and
hover read-out.
"""
from __future__ import annotations

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QFrame, QGraphicsDropShadowEffect, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QScrollBar, QVBoxLayout,
    QWidget,
)

from datetime import datetime, timedelta

from ..app_context import AppContext
from ..core.logging_config import get_logger
from ..core.money import format_money
from ..core.session import current_session
from ..services.dashboard_service import DashboardService

log = get_logger(__name__)


def _greeting() -> str:
    h = datetime.now().hour
    if h < 12:
        return "Good morning"
    if h < 17:
        return "Good afternoon"
    return "Good evening"


def _first_name() -> str:
    u = current_session.user
    full = (u.full_name or u.username) if u else ""
    return full.split()[0] if full else "there"

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

    def set_value(self, text: str, hint: str = "", color: str | None = None,
                  hint_color: str | None = None) -> None:
        self._value.setText(text)
        self._hint.setText(hint)
        self._value.setStyleSheet(f"color:{color or _INK};")
        self._hint.setStyleSheet(
            f"color:{hint_color or _FAINT};font-size:11px;"
            + ("font-weight:600;" if hint_color else ""))

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
    """A polished, dependency-free sales chart. Toggles between BAR and LINE/AREA.
    Features a currency y-axis with gridlines, peak + hover value labels, a hover
    tooltip (sales + invoices), the best day highlighted, and a `clicked(date)`
    signal (emitted in day granularity) so a click opens that day's DSR."""

    clicked = Signal(str)   # the clicked point's date (YYYY-MM-DD)

    def __init__(self) -> None:
        super().__init__()
        self._series: list[dict] = []
        self._sym = "Rs"
        self._mu = 100
        self._mode = "bar"          # 'bar' or 'line'
        self._granularity = "day"
        self._hover = -1
        self._slots: dict[int, QRectF] = {}   # global index -> hover/click column
        self._pts: dict[int, QPointF] = {}    # global index -> line marker centre
        self._vis_start = 0                   # first visible point (pan offset)
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        # When a range has more bars than fit comfortably, the chart shows a
        # readable WINDOW of them and this scrollbar pans it. Hidden when it fits.
        self.hbar = QScrollBar(Qt.Horizontal, self)
        self.hbar.hide()
        self.hbar.valueChanged.connect(self._on_scroll)
        self._stick_end = True                # new data starts scrolled to latest

    def _on_scroll(self, _v) -> None:
        self._stick_end = False
        self.update()

    def set_series(self, series, sym="Rs", mu=100, granularity="day") -> None:
        self._series = series or []
        self._sym = sym
        self._mu = mu
        self._granularity = granularity
        self._hover = -1
        self._stick_end = True                # show the most recent window first
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = "line" if mode == "line" else "bar"
        self.update()

    def _plot_rect(self) -> QRectF:
        # reserve bottom room for the zoom scrollbar when it's showing
        reserve = 18 if self.hbar.isVisible() else 0
        return QRectF(56, 22, self.width() - 56 - 16,
                      self.height() - 22 - 30 - reserve)

    # min pixels per bar/point before we switch to a scrollable window
    _MIN_SLOT = 26.0

    def _window(self, plot) -> tuple[int, int]:
        """Decide the visible slice [start, start+count). When everything fits,
        the whole series is shown and the scrollbar is hidden; otherwise a fixed
        auto-sized window of the widest readable size is shown and the scrollbar
        pans it."""
        n = len(self._series)
        count = max(8, int(plot.width() // self._MIN_SLOT))
        if count >= n:
            self.hbar.hide()
            self._vis_start = 0
            return 0, n
        max_start = n - count
        self.hbar.blockSignals(True)
        self.hbar.setMinimum(0)
        self.hbar.setMaximum(max_start)
        self.hbar.setPageStep(count)
        self.hbar.setSingleStep(1)
        if self._stick_end:
            self.hbar.setValue(max_start)         # newest window by default
        self.hbar.blockSignals(False)
        start = min(self.hbar.value(), max_start)
        self._vis_start = start
        self.hbar.setGeometry(int(plot.left()), self.height() - 16,
                              int(plot.width()), 14)
        self.hbar.show()
        return start, count

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.update()

    def _full_money(self, minor: int) -> str:
        return format_money(int(minor or 0), self._sym, self._mu)

    # -- paint --------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        plot = self._plot_rect()
        totals = [x.get("total", 0) for x in self._series]

        if not self._series or max(totals, default=0) == 0:
            self.hbar.hide()
            p.setPen(QColor(_FAINT))
            f = QFont(); f.setPointSize(10); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "No sales in this period.")
            p.end()
            return

        # Decide the visible window first (this shows/positions the zoom scrollbar),
        # then recompute the plot so its height accounts for the scrollbar strip.
        plot = self._plot_rect()
        vis_start, vis_count = self._window(plot)
        plot = self._plot_rect()
        vis_end = vis_start + vis_count

        # y-axis is scaled to the WHOLE range's peak so bars don't jump height as
        # you pan the window.
        top = _nice_ceil(max(totals))
        grid_pen = QPen(QColor(0, 0, 0, 16)); grid_pen.setWidthF(1.0)
        small = QFont(); small.setPointSize(8)
        p.setFont(small)
        for i in range(5):
            frac = i / 4
            y = plot.bottom() - frac * plot.height()
            p.setPen(grid_pen)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(_FAINT))
            p.drawText(QRectF(0, y - 8, plot.left() - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter,
                       _short_money(int(top * frac), self._mu, self._sym))

        slot = plot.width() / vis_count
        self._slots = {}
        self._pts = {}
        # the peak label is shown on the best day WITHIN the visible window
        best = max(range(vis_start, vis_end),
                   key=lambda i: self._series[i]["total"])
        # x-label thinning across the visible count so dates never collide
        fit = max(1, int(plot.width() // 62))
        lbl_step = max(1, -(-vis_count // fit))   # ceil(vis_count / fit)

        if self._mode == "line":
            self._paint_line(p, plot, top, best, slot, lbl_step, vis_start, vis_count)
        else:
            self._paint_bars(p, plot, top, best, slot, lbl_step, vis_start, vis_count)

        p.setPen(QPen(QColor(0, 0, 0, 32), 1.0))
        p.drawLine(plot.bottomLeft(), plot.bottomRight())

        if self._hover in self._slots or self._hover in self._pts:
            self._paint_tooltip(p, plot)
        p.end()

    def _bar_label(self, p, cx, slot, by, total, strong, plot) -> None:
        f = QFont(); f.setPointSize(8); f.setBold(True); p.setFont(f)
        p.setPen(QColor(_INK) if strong else QColor(_MUTE))
        # give the value its own comfortable width and keep it inside the plot so
        # the peak label never gets clipped at the chart's left/right edge
        w = 64.0
        left = min(max(cx - w / 2, plot.left()), plot.right() - w)
        p.drawText(QRectF(left, by - 17, w, 15),
                   Qt.AlignHCenter | Qt.AlignBottom,
                   _short_money(total, self._mu, self._sym))

    def _paint_bars(self, p, plot, top, best, slot, lbl_step, vis_start, vis_count) -> None:
        bar_w = min(46.0, slot * 0.6)
        dayf = QFont(); dayf.setPointSize(8)
        for li in range(vis_count):
            i = vis_start + li
            x = self._series[i]
            cx = plot.left() + slot * (li + 0.5)
            self._slots[i] = QRectF(plot.left() + slot * li, plot.top(),
                                    slot, plot.height())
            bh = (x["total"] / top) * plot.height() if top else 0
            by = plot.bottom() - bh
            bar = QRectF(cx - bar_w / 2, by, bar_w, max(bh, 0.0))
            hovered = (i == self._hover)
            is_best = (i == best)
            # Colour by the day/bucket's DSR cash net (in − out):
            #   0  -> green  (balanced — the money nets out)
            #   >0 -> yellow (cash left over / positive)
            #   <0 -> red    (short / negative)
            a0 = 255 if hovered else 235
            a1 = 255 if hovered else 205
            net = x.get("cash_net", 0)
            if net > 0:
                top0, bot0 = QColor(234, 179, 8, a0), QColor(253, 224, 71, a1)
            elif net < 0:
                top0, bot0 = QColor(220, 38, 38, a0), QColor(248, 113, 113, a1)
            else:
                top0, bot0 = QColor(22, 163, 74, a0), QColor(74, 222, 128, a1)
            grad = QLinearGradient(0, by, 0, plot.bottom())
            grad.setColorAt(0, top0)
            grad.setColorAt(1, bot0)
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
                p.setPen(Qt.NoPen); p.fillPath(path, grad)
            # value label only on the peak + hovered (keeps it uncluttered)
            if x["total"] > 0 and (is_best or hovered):
                self._bar_label(p, cx, slot, by, x["total"], hovered or is_best, plot)
            if li % lbl_step == 0 or hovered:
                p.setFont(dayf)
                p.setPen(QColor(_INK) if hovered else QColor(_FAINT))
                lw = slot * lbl_step           # room up to the next shown label
                p.drawText(QRectF(cx - lw / 2, plot.bottom() + 6, lw, 18),
                           Qt.AlignHCenter | Qt.AlignTop, str(x.get("label", "")))

    def _paint_line(self, p, plot, top, best, slot, lbl_step, vis_start, vis_count) -> None:
        self._pts = {}
        order = []
        for li in range(vis_count):
            i = vis_start + li
            x = self._series[i]
            cx = plot.left() + slot * (li + 0.5)
            cy = plot.bottom() - (x["total"] / top) * plot.height() if top else plot.bottom()
            pt = QPointF(cx, cy)
            self._pts[i] = pt
            self._slots[i] = QRectF(plot.left() + slot * li, plot.top(),
                                    slot, plot.height())
            order.append(pt)
        # area fill under the line
        area = QPainterPath()
        area.moveTo(order[0].x(), plot.bottom())
        for pt in order:
            area.lineTo(pt.x(), pt.y())
        area.lineTo(order[-1].x(), plot.bottom())
        area.closeSubpath()
        grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
        grad.setColorAt(0, QColor(37, 99, 235, 90))
        grad.setColorAt(1, QColor(37, 99, 235, 10))
        p.fillPath(area, grad)
        # the line
        line = QPainterPath(); line.moveTo(order[0])
        for pt in order[1:]:
            line.lineTo(pt)
        p.setPen(QPen(QColor(37, 99, 235), 2.2)); p.drawPath(line)
        # markers + labels
        dayf = QFont(); dayf.setPointSize(8)
        for li in range(vis_count):
            i = vis_start + li
            pt = self._pts[i]
            hovered = (i == self._hover); is_best = (i == best)
            if hovered or is_best:
                p.setBrush(QColor(22, 163, 74) if is_best else QColor(37, 99, 235))
                p.setPen(QPen(QColor("white"), 1.5))
                p.drawEllipse(pt, 4.2, 4.2)
                self._bar_label(p, pt.x(), slot, pt.y(), self._series[i]["total"],
                                True, plot)
            if li % lbl_step == 0 or hovered:
                p.setFont(dayf)
                p.setPen(QColor(_INK) if hovered else QColor(_FAINT))
                lw = slot * lbl_step
                p.drawText(QRectF(pt.x() - lw / 2, plot.bottom() + 6, lw, 18),
                           Qt.AlignHCenter | Qt.AlignTop, str(self._series[i].get("label", "")))

    def _paint_tooltip(self, p, plot) -> None:
        x = self._series[self._hover]
        net = x.get("cash_net", 0)
        net_word = "balanced" if net == 0 else ("positive" if net > 0 else "short")
        lines = [str(x.get("label", "")),
                 "Sales: " + self._full_money(x.get("total", 0)),
                 f"Invoices: {x.get('n', 0)}",
                 f"Cash in−out: {self._full_money(net)} ({net_word})"]
        fm = QFontMetrics(QFont())
        w = max(fm.horizontalAdvance(s) for s in lines) + 18
        h = 18 * len(lines) + 10
        if self._mode == "line" and self._hover in self._pts:
            anchor = self._pts[self._hover]
        else:
            r = self._slots.get(self._hover)
            if r is None:
                return
            anchor = QPointF(r.center().x(), plot.top() + 10)
        tx = min(max(anchor.x() + 10, plot.left()), plot.right() - w)
        ty = max(anchor.y() - h - 8, plot.top())
        box = QRectF(tx, ty, w, h)
        p.setBrush(QColor(17, 24, 39, 235)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("white"))
        f = QFont(); f.setPointSize(8); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(tx + 9, ty + 5, w - 18, 18), Qt.AlignLeft, lines[0])
        f.setBold(False); p.setFont(f)
        for k, s in enumerate(lines[1:], start=1):
            p.drawText(QRectF(tx + 9, ty + 5 + 18 * k, w - 18, 18), Qt.AlignLeft, s)

    # -- interaction --------------------------------------------------
    def _idx_at(self, x) -> int:
        for i, r in self._slots.items():
            if r.left() <= x <= r.right():
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        idx = self._idx_at(e.position().x())
        if idx != self._hover:
            self._hover = idx
            self.setCursor(Qt.PointingHandCursor if (idx >= 0 and self._granularity == "day")
                           else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        idx = self._idx_at(e.position().x())
        if idx >= 0 and self._granularity == "day":
            self.clicked.emit(self._series[idx].get("date", ""))

    def leaveEvent(self, e) -> None:  # noqa: N802
        if self._hover != -1:
            self._hover = -1
            self.setCursor(Qt.ArrowCursor)
            self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        # when windowed (scrollbar visible), the wheel pans the window
        if self.hbar.isVisible():
            step = -1 if e.angleDelta().y() > 0 else 1
            self.hbar.setValue(self.hbar.value() + step * 3)
            e.accept()
        else:
            super().wheelEvent(e)


class DashboardView(QWidget):
    def __init__(self, ctx: AppContext, navigate=None) -> None:
        super().__init__()
        self.ctx = ctx
        self.navigate = navigate
        self.svc = DashboardService(ctx.db)
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
        greet_box = QVBoxLayout()
        greet_box.setSpacing(1)
        self._greeting = QLabel(f"{_greeting()}, {_first_name()}")
        self._greeting.setObjectName("PageTitle")
        greet_box.addWidget(self._greeting)
        self._greeting_sub = QLabel(datetime.now().strftime("%A, %d %B %Y"))
        self._greeting_sub.setObjectName("Muted")
        greet_box.addWidget(self._greeting_sub)
        header.addLayout(greet_box)
        header.addStretch(1)
        # date RANGE — the dashboard shows analytics for [From, To]. Quick
        # presets (Today / Week / Month) just fill the two pickers.
        today = QDate.currentDate()
        header.addWidget(QLabel("From"))
        self._from = QDateEdit()
        self._from.setCalendarPopup(True)
        self._from.setDisplayFormat("dd MMM yyyy")
        self._from.setMaximumDate(today)
        self._from.setDate(today)
        self._from.dateChanged.connect(lambda _=None: self.refresh())
        header.addWidget(self._from)
        header.addSpacing(4)
        header.addWidget(QLabel("To"))
        self._to = QDateEdit()
        self._to.setCalendarPopup(True)
        self._to.setDisplayFormat("dd MMM yyyy")
        self._to.setMaximumDate(today)
        self._to.setDate(today)
        self._to.dateChanged.connect(lambda _=None: self.refresh())
        header.addWidget(self._to)
        header.addSpacing(8)
        for _lbl, _preset in (("Today", "today"), ("Week", "week"), ("Month", "month")):
            chip = QPushButton(_lbl)
            chip.setObjectName("Chip")
            chip.clicked.connect(lambda _=False, p=_preset: self._apply_preset(p))
            header.addWidget(chip)
        header.addSpacing(10)
        # quick light/dark toggle — available to everyone, right on the dashboard
        self._mode = "dark" if str(
            self.ctx.company.get_company().get("theme") or "light").lower() == "dark" \
            else "light"
        self._theme_btn = QPushButton("")
        self._theme_btn.setObjectName("Secondary")
        self._theme_btn.setCursor(Qt.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        self._sync_theme_btn()
        header.addWidget(self._theme_btn)
        header.addSpacing(6)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("Secondary")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)

        # software-update notification (hidden until an update is available)
        self._update_banner = _UpdateBanner()
        self._update_banner.hide()
        root.addWidget(self._update_banner)

        # negative-stock alert (hidden unless a product sits below zero)
        self._neg_banner = QPushButton("")
        self._neg_banner.setCursor(Qt.PointingHandCursor)
        self._neg_banner.setStyleSheet(
            "QPushButton{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;"
            "border-radius:8px;padding:9px 14px;text-align:left;font-weight:600;}"
            "QPushButton:hover{background:#fee2e2;}")
        self._neg_banner.clicked.connect(
            lambda: self.navigate("products", "negative_products")
            if self.navigate else None)
        self._neg_banner.hide()
        root.addWidget(self._neg_banner)

        nav = self.navigate
        grid = QGridLayout()
        grid.setSpacing(18)
        # (attr, title, accent, icon, nav_key)
        specs = [
            ("card_sales", "Sales", "#2563eb", "bars", "sales"),
            ("card_profit", "Profit", "#16a34a", "up", "reports"),
            ("card_cash", "Cash in Hand (system)", "#0f766e", "bars", "reports"),
            ("card_actual", "Actual Cash (last count)", "#b45309", "bars", "reports"),
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

        # quick actions: Day Close report + end-of-day drawer count
        count_row = QHBoxLayout()
        count_row.addStretch(1)
        self._dsr_btn = QPushButton("  Day Close (DSR)")
        self._dsr_btn.setObjectName("Secondary")
        self._dsr_btn.setToolTip("Open the Daily Sales Report for a chosen day")
        self._dsr_btn.clicked.connect(self._open_day_close)
        count_row.addWidget(self._dsr_btn)
        self._count_btn = QPushButton("  Count drawer (end of day)")
        self._count_btn.setObjectName("Secondary")
        self._count_btn.setToolTip("Enter the cash counted in the drawer and "
                                   "compare it to the system")
        self._count_btn.clicked.connect(self._open_cash_count)
        count_row.addWidget(self._count_btn)
        root.addLayout(count_row)

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

        chead = QHBoxLayout()
        tbox = QVBoxLayout(); tbox.setSpacing(1)
        self._chart_title = QLabel("Sales")
        self._chart_title.setStyleSheet(f"font-size:15px;font-weight:700;color:{_INK};")
        self._chart_sub = QLabel("")
        self._chart_sub.setStyleSheet(f"color:{_FAINT};font-size:11px;")
        tbox.addWidget(self._chart_title)
        tbox.addWidget(self._chart_sub)
        chead.addLayout(tbox)
        chead.addStretch(1)
        # segmented toggles: chart type (bar/line) and granularity (D/W/M)
        self._chart_mode = "bar"
        self._chart_gran = "day"
        self._mode_grp, mode_w = self._segmented(
            [("Bar", "bar"), ("Line", "line")], "bar", self._on_mode)
        chead.addWidget(mode_w)
        chead.addSpacing(10)
        self._gran_grp, gran_w = self._segmented(
            [("Day", "day"), ("Week", "week"), ("Month", "month")], "day", self._on_gran)
        chead.addWidget(gran_w)
        cl.addLayout(chead)

        self.chart = _SalesChart()
        self.chart.clicked.connect(self._open_day_from_chart)
        cl.addWidget(self.chart, 1)
        root.addWidget(chart_card)

        lists = QHBoxLayout()
        lists.setSpacing(18)
        self.top_card = _ListCard("Top Sellers", accent="#16a34a")
        self.recent_card = _ListCard("Recent Sales", accent="#2563eb")
        self.low_card = _ListCard("Low Stock Items", accent="#f59e0b")
        lists.addWidget(self.top_card, 1)
        lists.addWidget(self.recent_card, 1)
        lists.addWidget(self.low_card, 1)
        root.addLayout(lists, 1)

    def set_update_banner(self, text: str, on_click) -> None:
        self._update_banner.set(text, on_click)
        self._update_banner.show()

    def clear_update_banner(self) -> None:
        self._update_banner.hide()

    def _open_cash_count(self) -> None:
        from .cash_count_dialog import CashCountDialog
        CashCountDialog(self.ctx, self).exec()
        self.refresh()   # a saved count doesn't change cash, but keep the view fresh

    def _open_day_close(self) -> None:
        from .day_close_dialog import DayCloseDialog
        DayCloseDialog(self.ctx, self).exec()

    # -- sales chart toggles ------------------------------------------
    def _segmented(self, options, default, on_change):
        """Build a small segmented toggle (checkable buttons in a group). Returns
        (QButtonGroup, container QWidget). on_change(value) fires on selection."""
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        grp = QButtonGroup(wrap)
        grp.setExclusive(True)
        for label, value in options:
            b = QPushButton(label)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(value == default)
            b.setProperty("seg_value", value)
            grp.addButton(b)
            row.addWidget(b)
        grp.buttonClicked.connect(
            lambda btn: on_change(btn.property("seg_value")))
        return grp, wrap

    def _on_mode(self, value) -> None:
        self._chart_mode = value
        self.chart.set_mode(value)

    def _on_gran(self, value) -> None:
        self._chart_gran = value
        self._apply_chart()

    def _apply_chart(self) -> None:
        """(Re)build the sales series for the current window + granularity and
        push it to the chart. Called on refresh and whenever a toggle changes."""
        if not hasattr(self, "_win_from"):
            return
        series = self.svc.chart_series(self._win_from, self._win_to, self._chart_gran)
        total = sum(x.get("total", 0) for x in series)
        per = {"day": "day", "week": "week", "month": "month"}[self._chart_gran]
        self._chart_sub.setText(
            f"Gross sales per {per}  ·  total "
            + format_money(total, self._chart_sym, self._chart_mu))
        self.chart.set_series(series, self._chart_sym, self._chart_mu,
                              granularity=self._chart_gran)
        self.chart.set_mode(self._chart_mode)

    def _open_day_from_chart(self, day: str) -> None:
        if not day:
            return
        from .day_close_dialog import DayCloseDialog
        DayCloseDialog(self.ctx, self, day=day).exec()

    def _apply_preset(self, preset: str) -> None:
        """Fill the From/To pickers from a quick preset, then refresh once."""
        today = QDate.currentDate()
        if preset == "week":                       # this week to date (Mon–today)
            start = today.addDays(-(today.dayOfWeek() - 1))
        elif preset == "month":                    # this month to date (1st–today)
            start = QDate(today.year(), today.month(), 1)
        else:                                      # today
            start = today
        self._from.blockSignals(True)
        self._to.blockSignals(True)
        self._from.setDate(start)
        self._to.setDate(today)
        self._from.blockSignals(False)
        self._to.blockSignals(False)
        self.refresh()

    def _sync_theme_btn(self) -> None:
        """Label the toggle with the mode it will switch TO."""
        self._theme_btn.setText("Light mode" if self._mode == "dark" else "Dark mode")

    def _toggle_theme(self) -> None:
        """Flip the shop theme and apply it live across the whole app. Available
        to any signed-in user (theme is a cosmetic, shop-wide preference)."""
        from PySide6.QtWidgets import QApplication
        from ..ui.theme import apply_theme
        self._mode = "light" if self._mode == "dark" else "dark"
        try:
            self.ctx.company.update_company({"theme": self._mode})
        except Exception:
            log.exception("Could not save theme preference")
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._mode)
        self._sync_theme_btn()

    def refresh(self) -> None:
        # keep the toggle in sync if the theme changed elsewhere (e.g. Settings)
        self._mode = "dark" if str(
            self.ctx.company.get_company().get("theme") or "light").lower() == "dark" \
            else "light"
        self._sync_theme_btn()
        # keep the greeting current (time of day + who is signed in)
        self._greeting.setText(f"{_greeting()}, {_first_name()}")
        self._greeting_sub.setText(datetime.now().strftime("%A, %d %B %Y"))
        c = self.ctx.company.get_company()
        sym = c.get("currency_symbol", "Rs")
        mu = c.get("currency_minor_units", 100)

        def m(v):
            return format_money(v, sym, mu)

        # pass both dates; the service orders them, so an inverted pair is safe
        d_from = self._from.date().toString("yyyy-MM-dd")
        d_to = self._to.date().toString("yyyy-MM-dd")
        s = self.svc.summary(d_from, d_to)
        d = self.svc.deltas(d_from, d_to)
        win_lbl = self._window_label(s.get("window_start"), s.get("window_end"))
        plabel = f"in {win_lbl}"

        def trend(pct, *, up_is_good=True):
            """(hint text, colour) for a delta. up_is_good flips the colour for
            expenses, where a rise is bad."""
            if pct is None:
                return d["label"], None
            arrow = "▲" if pct >= 0 else "▼"
            good = (pct >= 0) if up_is_good else (pct < 0)
            color = "#16a34a" if good else "#dc2626"
            return f"{arrow} {abs(pct):.0f}%  {d['label']}", color

        h, hc = trend(d["sales_pct"])
        self.card_sales.set_value(m(s["today_sales_minor"]), h, hint_color=hc)
        h, hc = trend(d["profit_pct"])
        self.card_profit.set_value(m(s["today_profit_minor"]), h,
                                   color="#16a34a", hint_color=hc)
        ends_today = self._to.date() == QDate.currentDate()
        cash_hint = "total business cash" if ends_today else f"as of {s.get('window_end')}"
        self.card_cash.set_value(m(s.get("cash_in_hand_minor", 0)),
                                 cash_hint, color="#0f766e")
        # Actual vs system: the last physical drawer count and its difference
        lc = self.svc.last_cash_count()
        if lc:
            diff = lc["difference_minor"]
            when = lc.get("count_date") or ""
            if diff == 0:
                hint, col = f"balanced · {when}", "#16a34a"
            else:
                word = "over" if diff > 0 else "short"
                hint = f"{word} {m(abs(diff))} · {when}"
                col = "#b45309" if diff > 0 else "#dc2626"
            self.card_actual.set_value(m(lc["counted_minor"]), hint, color=col)
        else:
            self.card_actual.set_value("—", "no count yet — use Count drawer")
        h, hc = trend(d["expenses_pct"], up_is_good=False)
        self.card_expenses.set_value(m(s["today_expenses_minor"]), h,
                                     color="#ef4444" if s["today_expenses_minor"] else None,
                                     hint_color=hc)
        self.card_stock.set_value(m(s["stock_value_minor"]), "at cost")
        low_n = s["low_stock_count"]
        self.card_low.set_value(str(low_n), "at/below minimum",
                                color="#b45309" if low_n else None)
        self.card_products.set_value(str(s["inactive_product_count"]), "inactive")

        top = self.svc.top_sellers(d_from, d_to, 6)
        self.top_card.set_rows(
            [(t["name"], f"{t['qty']} sold") for t in top],
            f"No sales {plabel}.")

        sales = self.svc.sales_in_window(d_from, d_to, 6)
        self.recent_card.set_rows(
            [(f"{r['invoice_no']}   ·   {(r.get('sale_date') or '')[:16]}",
              m(r["grand_total_minor"])) for r in sales],
            f"No sales {plabel}.")

        # negative-stock alert banner + fold negatives into the low-stock list
        neg = self.svc.negative_stock(8)
        neg_count = self.svc.negative_stock_count()
        if neg_count:
            shown = ", ".join(f"{r['name']} ({r['stock_qty']})" for r in neg[:4])
            more = "" if neg_count <= 4 else f"   +{neg_count - 4} more"
            self._neg_banner.setText(
                f"⚠  {neg_count} product(s) at negative stock — sold from the "
                f"warehouse, awaiting purchase:   {shown}{more}")
            self._neg_banner.show()
        else:
            self._neg_banner.hide()

        neg_names = {r["name"] for r in neg}
        low = [r for r in self.svc.recent_low_stock(8) if r["name"] not in neg_names]
        rows = [(r["name"], str(r["stock_qty"]), "#dc2626") for r in neg]
        rows += [(r["name"], f"{r['stock_qty']} / {r['min_stock_level']}", "#dc2626")
                 for r in low]
        self.low_card.set_rows(rows[:8], "Nothing low on stock.")

        # remember the window + currency so the chart toggles can re-fetch
        self._win_from, self._win_to, self._win_lbl = d_from, d_to, win_lbl
        self._chart_sym, self._chart_mu = sym, mu
        self._chart_title.setText(f"Sales — {win_lbl}")
        self._apply_chart()

    @staticmethod
    def _window_label(start: str | None, end: str | None) -> str:
        """Human label for the selected range: a single date ('12 Jan 2026'), a
        full calendar month ('January 2026'), or a plain range ('12 Jan – 20 Jan
        2026')."""
        if not start or not end:
            return "this period"
        try:
            sd = datetime.strptime(start, "%Y-%m-%d")
            ed = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return "this period"
        if start == end:
            return sd.strftime("%d %b %Y")
        if sd.day == 1 and (ed + timedelta(days=1)).day == 1 and sd.month == ed.month \
                and sd.year == ed.year:
            return sd.strftime("%B %Y")
        left = sd.strftime("%d %b") + (sd.strftime(" %Y") if sd.year != ed.year else "")
        return f"{left} – {ed.strftime('%d %b %Y')}"
