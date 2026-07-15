"""Update controller: runs the network check/download off the UI thread and
reports back via Qt signals (auto-queued to the main thread).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from ..app_context import AppContext
from ..core.logging_config import get_logger
from ..services.update_service import UpdateError, UpdateService

log = get_logger(__name__)


class UpdateController(QObject):
    checked = Signal(object)        # dict(info) or None (up to date)
    check_failed = Signal(str)
    progress = Signal(int)          # 0..100
    downloaded = Signal(str)        # installer path
    download_failed = Signal(str)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.svc = UpdateService(ctx)

    def should_check_today(self) -> bool:
        return self.svc.should_check_today()

    # -- check --------------------------------------------------------
    def check_async(self) -> None:
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        try:
            self.checked.emit(self.svc.check())
        except UpdateError as exc:
            self.check_failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            log.exception("Update check crashed")
            self.check_failed.emit(f"Update check failed: {exc}")

    # -- download -----------------------------------------------------
    def download_async(self, info: dict) -> None:
        threading.Thread(target=self._download, args=(info,), daemon=True).start()

    def _download(self, info: dict) -> None:
        try:
            path = self.svc.download(info, progress_cb=self.progress.emit)
            self.downloaded.emit(str(path))
        except Exception as exc:
            self.download_failed.emit(str(exc))

    def launch_installer(self, path: str) -> None:
        self.svc.launch_installer(path)
