"""Show money fields EMPTY at zero instead of a misleading "0.00".

Every amount/price field in the app is a QDoubleSpinBox, which always paints a
value — so an untouched field reads "Rs 0.00", which looks like a real amount and
invites fat-finger errors (people type onto the zeros and end up with extra
digits). Qt can blank a spin box when it sits at its minimum via
setSpecialValueText(); we switch that on for every money spin box (minimum 0) so
it appears empty until a number is entered, then shows the amount normally.

Applied app-wide through one event filter on the QApplication (installed in
main.py next to WheelGuard), so it also covers dialogs created later. A single
space is used as the "blank" text because an empty string disables the feature
in Qt.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QDoubleSpinBox

_BLANK = " "   # looks empty; "" would turn the feature off


class MoneyBlankGuard(QObject):
    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if event.type() == QEvent.Polish and isinstance(obj, QDoubleSpinBox):
            # only when it can actually sit at 0, and hasn't set its own text
            if obj.minimum() == 0 and not obj.specialValueText():
                obj.setSpecialValueText(_BLANK)
        return False
