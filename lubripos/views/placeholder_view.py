"""Generic placeholder page used for modules not yet implemented.

Each future build step replaces these with real views (Products, POS, etc.).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderView(QWidget):
    def __init__(self, title: str, note: str = "Coming in a later build step.") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        t = QLabel(title)
        t.setObjectName("PageTitle")
        n = QLabel(note)
        n.setObjectName("Muted")
        layout.addWidget(t)
        layout.addWidget(n)
        layout.addStretch(1)
