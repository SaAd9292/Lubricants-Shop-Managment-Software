"""Penguix application entry point.

Run from the project root:
    python main.py

Flow: build app context (DB init + seed) -> show login -> on success show the
main window. Logging out returns to the login screen; closing the main window
exits the app.
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from lubripos import __app_name__
from lubripos.app_context import AppContext
from lubripos.config import resource_path
from lubripos.core.i18n import set_language
from lubripos.ui.theme import apply_theme
from lubripos.views.login_view import LoginDialog
from lubripos.views.main_window import MainWindow


def _set_windows_app_id() -> None:
    """Give Windows an explicit AppUserModelID so the taskbar shows our icon
    (and groups windows under Penguix) instead of the generic Python icon."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Penguix.POS")
        except Exception:
            pass


def _install_crash_handler(ctx) -> None:
    """Log any unhandled exception and tell the user where the log is, instead
    of the app silently dying. The POS keeps running where it can."""
    from lubripos.core.logging_config import get_logger
    log = get_logger("crash")
    log_path = ctx.config.logs_dir / "lubripos.log"

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "Unexpected error",
                "Penguix hit an unexpected error and saved the details to a log.\n\n"
                f"Log file:\n{log_path}\n\n"
                "Please send this file to support. You can keep working; if the "
                "app behaves oddly, restart it.")
        except Exception:
            pass

    sys.excepthook = _hook


def main() -> int:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)

    icon = QIcon(str(resource_path("assets", "penguix.ico")))
    if not icon.isNull():
        app.setWindowIcon(icon)   # applies to every window + the taskbar

    apply_theme(app)

    ctx = AppContext()
    _install_crash_handler(ctx)
    try:
        while True:
            # pick up the shop's chosen UI language (re-read each login
            # so an admin's change applies after logging out)
            set_language(ctx.company.get_company().get("language"))
            login = LoginDialog(ctx)
            if icon.isNull() is False:
                login.setWindowIcon(icon)
            if login.exec() != QDialog.Accepted:
                break  # user cancelled login -> quit

            window = MainWindow(ctx, app)
            if not icon.isNull():
                window.setWindowIcon(icon)
            window.show()
            app.exec()

            if not getattr(window, "_logged_out", False):
                break  # window closed (not a logout) -> quit
    finally:
        ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
