"""Reusable UI widgets shared across screens."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QTableWidget


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
