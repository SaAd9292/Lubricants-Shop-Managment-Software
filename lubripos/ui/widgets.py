"""Reusable UI widgets shared across screens."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox, QHBoxLayout, QLayout, QSpinBox, QTableWidget, QWidget,
)

from ..core.packs import split_packs


class CartonQtyEntry(QWidget):
    """Enter a quantity as cartons + loose pieces, exposing a single piece count.

    For a product sold in cartons (units_per_carton > 1) it shows two spin boxes
    ('N ctn' + 'M pc'); for loose/drum items (<= 1) just a piece box. Used at the
    till-side counting screens (purchases, stock adjust) so staff enter stock the
    way it sits on the shelf while the database keeps a single piece count."""

    valueChanged = Signal()

    def __init__(self, units_per_carton=1, parent=None) -> None:
        super().__init__(parent)
        self.upc = max(1, int(units_per_carton or 1))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.cartons = None
        if self.upc > 1:
            self.cartons = QSpinBox()
            self.cartons.setRange(0, 100_000_000)
            self.cartons.setSuffix(" ctn")
            self.cartons.setButtonSymbols(QAbstractSpinBox.NoButtons)
            self.cartons.valueChanged.connect(self.valueChanged)
            lay.addWidget(self.cartons)
        self.pieces = QSpinBox()
        self.pieces.setRange(0, 100_000_000)
        self.pieces.setSuffix(" pc")
        self.pieces.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.pieces.valueChanged.connect(self.valueChanged)
        lay.addWidget(self.pieces)

    def total_pieces(self) -> int:
        n = self.pieces.value()
        if self.cartons is not None:
            n += self.cartons.value() * self.upc
        return n

    def set_total(self, qty) -> None:
        cartons, loose = split_packs(qty, self.upc)
        if self.cartons is not None:
            self.cartons.setValue(cartons)
            self.pieces.setValue(loose)
        else:
            self.pieces.setValue(int(qty or 0))


class DataTable(QTableWidget):
    """A QTableWidget that shows a friendly placeholder when it has no rows.

    Set `.placeholder` to the message to display (UX: empty-states). The text is
    painted centered over the empty viewport, so no extra layout plumbing is
    needed in each screen.
    """

    placeholder = "Nothing here yet."

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        super().paintEvent(event)
        if self.rowCount() == 0 and self.placeholder:
            painter = QPainter(self.viewport())
            painter.save()
            painter.setPen(QColor("#94a3b8"))
            f = self.font()
            f.setPointSizeF(f.pointSizeF() + 1)
            painter.setFont(f)
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, self.placeholder)
            painter.restore()


class FlowLayout(QLayout):
    """A layout that lays widgets left-to-right and WRAPS to the next line when
    it runs out of width (Qt's classic flow-layout example). Used for payment
    chips so their labels never get clipped in a narrow panel."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 6) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items: list = []

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, *, test_only: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            next_x = x + w + self._spacing
            if next_x - self._spacing > rect.right() and line_h > 0:
                x = rect.x()
                y = y + line_h + self._spacing
                next_x = x + w + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x = next_x
            line_h = max(line_h, h)
        return y + line_h - rect.y()
