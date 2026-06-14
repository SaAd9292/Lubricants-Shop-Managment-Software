"""Application configuration and cross-platform path resolution.

All writable state (database, logs, backups) lives OUTSIDE the program
directory so the app works whether installed in Program Files, /opt, or
run from source. Override the base location with the LUBRIPOS_HOME env var.

The app data folder is named after APP_NAME. If the app was previously run
under an older name (see LEGACY_APP_NAMES), the old folder is migrated to the
new location on first launch so existing data/backups are preserved.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Penguix"
LEGACY_APP_NAMES = ["LubriPOS"]  # older names to migrate data from


def _data_root_for(name: str) -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / name


def _default_data_root() -> Path:
    env = os.environ.get("LUBRIPOS_HOME")
    if env:
        return Path(env).expanduser()
    return _data_root_for(APP_NAME)


class Config:
    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root: Path = Path(data_root) if data_root else _default_data_root()
        self.db_path: Path = self.data_root / "lubripos.db"
        self.backups_dir: Path = self.data_root / "backups"
        self.logs_dir: Path = self.data_root / "logs"
        self.assets_dir: Path = self.data_root / "assets"

    def _migrate_legacy_dir(self) -> None:
        """If a previous app-name folder exists and ours doesn't, move it over."""
        if os.environ.get("LUBRIPOS_HOME"):
            return  # explicit override: don't touch
        if self.data_root.exists():
            return
        for legacy in LEGACY_APP_NAMES:
            old = _data_root_for(legacy)
            if old.is_dir() and old != self.data_root:
                try:
                    self.data_root.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old), str(self.data_root))
                    print(f"[Penguix] Migrated data from {old} -> {self.data_root}")
                except Exception as exc:  # pragma: no cover
                    print(f"[Penguix] Could not migrate legacy data ({exc}); "
                          f"starting fresh at {self.data_root}")
                return

    def ensure_dirs(self) -> None:
        self._migrate_legacy_dir()
        for d in (self.data_root, self.backups_dir, self.logs_dir, self.assets_dir):
            d.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Config data_root={self.data_root}>"


def resource_path(*parts: str) -> Path:
    """Locate a bundled resource (e.g. the app icon).

    In a PyInstaller build, data files are unpacked to sys._MEIPASS; in dev they
    sit next to the project root. Works in both.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(__file__).resolve().parents[1]
    return Path(base) / Path(*parts)
