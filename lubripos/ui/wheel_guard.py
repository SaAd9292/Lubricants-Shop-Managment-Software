"""Guard against accidental mouse-wheel edits.

Qt spin boxes, date editors and combo boxes change their value when the wheel
is scrolled over them — even if they aren't focused. On a form that means
scrolling the dialog can silently bump a price, quantity, amount or a date (e.g.
a purchase date jumping to next year) without the user noticing.

This app-wide event filter blocks the wheel on those widgets UNLESS they are
focused. Deliberate adjustment still works: click into the field first, then
scroll (or use the arrows / type / calendar). Install once on the QApplication.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

# QDateEdit/QDateTimeEdit and QSpinBox/QDoubleSpinBox all derive from
# QAbstractSpinBox, so that one base covers every numeric/date editor.
_GUARDED = (QAbstractSpinBox, QComboBox)


class WheelGuard(QObject):
    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if event.type() == QEvent.Wheel and isinstance(obj, _GUARDED):
            if not obj.hasFocus():
                return True   # swallow: no accidental value change
        return False
