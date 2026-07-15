"""On-screen numeric keypad for touchscreen mode.

Types into whichever numeric field currently has focus (the barcode box,
discount, price, quantity, amount). The keys use Qt.NoFocus so tapping them
never steals focus from the field being edited — that's what makes a single
shared keypad work across every input on the Sale screen.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QGridLayout, QLineEdit, QPushButton, QWidget,
)

# label -> (Qt key, text to insert). Special labels handled separately.
_KEYS = {
    "7": (Qt.Key_7, "7"), "8": (Qt.Key_8, "8"), "9": (Qt.Key_9, "9"),
    "4": (Qt.Key_4, "4"), "5": (Qt.Key_5, "5"), "6": (Qt.Key_6, "6"),
    "1": (Qt.Key_1, "1"), "2": (Qt.Key_2, "2"), "3": (Qt.Key_3, "3"),
    ".": (Qt.Key_Period, "."), "0": (Qt.Key_0, "0"),
}


class NumericKeypad(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        layout = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            (".", 3, 0), ("0", 3, 1), ("⌫", 3, 2),
        ]
        for label, r, c in layout:
            grid.addWidget(self._btn(label), r, c)
        clear = self._btn("Clear")
        grid.addWidget(clear, 4, 0, 1, 2)
        grid.addWidget(self._btn("Enter"), 4, 2)

    def _btn(self, label: str) -> QPushButton:
        b = QPushButton(label)
        b.setFocusPolicy(Qt.NoFocus)   # never steal focus from the edited field
        b.setMinimumHeight(44)
        b.clicked.connect(lambda _=False, t=label: self._press(t))
        return b

    # -- key dispatch -------------------------------------------------
    def _target(self):
        w = QApplication.focusWidget()
        return w if isinstance(w, (QLineEdit, QAbstractSpinBox)) else None

    def _send(self, w, key: int, text: str = "") -> None:
        QApplication.postEvent(w, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))
        QApplication.postEvent(w, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, text))

    def _press(self, label: str) -> None:
        w = self._target()
        if w is None:
            return
        if label == "⌫":
            self._send(w, Qt.Key_Backspace)
        elif label == "Enter":
            self._send(w, Qt.Key_Return, "\r")
        elif label == "Clear":
            if isinstance(w, QAbstractSpinBox):
                w.setValue(w.minimum())
            else:
                w.clear()
        else:
            key, text = _KEYS[label]
            self._send(w, key, text)
