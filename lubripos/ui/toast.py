"""Lightweight toast notifications — a non-blocking alternative to a modal
QMessageBox for routine success/info feedback.

Usage from any view:

    from ..ui.toast import show_toast
    show_toast(self, "Settings saved")
    show_toast(self, "Couldn't reach the server", kind="error")

The toast floats over the bottom-centre of the top-level window, fades in, holds
briefly, then fades out and deletes itself. It never steals focus or blocks the
UI. All failures are swallowed — a toast must never break a real action.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

# kind -> (background, foreground)
_KINDS = {
    "success": ("#16a34a", "#ffffff"),
    "error": ("#dc2626", "#ffffff"),
    "info": ("#334155", "#ffffff"),
}


class _Toast(QLabel):
    def __init__(self, host: QWidget, text: str, kind: str) -> None:
        super().__init__(text, host)
        bg, fg = _KINDS.get(kind, _KINDS["info"])
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:11px;"
            "padding:11px 20px; font-size:13px; font-weight:600;")
        self.setAlignment(Qt.AlignCenter)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._anim = QPropertyAnimation(self._eff, b"opacity", self)

    def _place(self) -> None:
        self.adjustSize()
        host = self.parentWidget()
        if host is None:
            return
        x = (host.width() - self.width()) // 2
        y = host.height() - self.height() - 44
        self.move(max(8, x), max(8, y))

    def run(self, msecs: int) -> None:
        self._place()
        self.show()
        self.raise_()
        self._eff.setOpacity(0.0)
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        QTimer.singleShot(max(600, msecs), self._fade_out)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setDuration(320)
        self._anim.setStartValue(self._eff.opacity())
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


def show_toast(widget: QWidget, text: str, kind: str = "success",
               msecs: int = 2400) -> None:
    """Show a toast anchored to `widget`'s top-level window. `kind` is one of
    'success' | 'error' | 'info'. Safe to call from anywhere."""
    try:
        if widget is None:
            return
        host = widget.window()
        if host is None:
            return
        _Toast(host, text, kind).run(msecs)
    except Exception:
        pass
