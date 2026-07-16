"""Auto-update: check a signed manifest, download + verify the installer, launch it.

Trust model (Ed25519-signed manifest):
  * The manifest is JSON: {"data": {version,url,sha256,notes}, "sig": "<hex>"}.
  * `sig` signs the CANONICAL bytes of `data` (sorted keys, no spaces).
  * The app verifies `sig` with the embedded PUBLIC key before trusting anything,
    then verifies the downloaded installer's SHA-256 matches data["sha256"].
  * So a tampered installer OR a tampered manifest is rejected — even if GitHub
    (the host) is compromised — because the attacker lacks the private seed.

The database lives in AppData (separate from the program files), so installing an
update never touches shop data; migrations run on the next launch.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

from .. import __version__
from ..core import ed25519
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from .update_config import MANIFEST_URL, UPDATE_PUBLIC_KEY_HEX

log = get_logger(__name__)


class UpdateError(LubriPosError):
    """Network, parsing, or signature-verification failure during update check."""


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in str(v).strip().lstrip("vV").split("."):
        num = "".join(c for c in chunk if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return _parse_version(remote) > _parse_version(local)


class UpdateService:
    def __init__(self, ctx=None) -> None:
        self.ctx = ctx
        self._pubkey = bytes.fromhex(UPDATE_PUBLIC_KEY_HEX)
        # throttle stamp is a FILE, not the DB: the update check runs on a
        # background thread and SQLite connections are bound to their creating
        # thread, so DB access here would crash. A file is thread-safe.
        self._stamp = None
        if ctx is not None:
            try:
                self._stamp = Path(ctx.config.data_root) / "update_last_check.txt"
            except Exception:
                self._stamp = None

    # -- once-a-day throttle (stored in app_meta) --------------------
    def should_check_today(self) -> bool:
        if not self._stamp:
            return True
        try:
            return self._stamp.read_text(encoding="utf-8").strip() != date.today().isoformat()
        except OSError:
            return True

    def mark_checked(self) -> None:
        if not self._stamp:
            return
        try:
            self._stamp.write_text(date.today().isoformat(), encoding="utf-8")
        except OSError:
            pass

    # -- manifest ----------------------------------------------------
    def _fetch_manifest(self) -> dict:
        try:
            req = urllib.request.Request(
                MANIFEST_URL, headers={"User-Agent": "Penguix-Updater"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise UpdateError(f"Could not reach the update server: {exc}") from exc

    def _verify_manifest(self, manifest: dict) -> dict:
        data, sig = manifest.get("data"), manifest.get("sig")
        if not isinstance(data, dict) or not isinstance(sig, str):
            raise UpdateError("Update manifest is malformed.")
        try:
            ok = ed25519.verify(_canonical(data), bytes.fromhex(sig), self._pubkey)
        except ValueError:
            ok = False
        if not ok:
            raise UpdateError("Update signature is invalid — refusing this update.")
        return data

    def check(self) -> dict | None:
        """Return {version,url,sha256,notes} if a verified newer version exists,
        else None. Raises UpdateError on network/verification problems."""
        data = self._verify_manifest(self._fetch_manifest())
        self.mark_checked()
        remote = str(data.get("version", "0"))
        if not is_newer(remote):
            log.info("Update check: up to date (local %s, remote %s)", __version__, remote)
            return None
        if not data.get("url") or not data.get("sha256"):
            raise UpdateError("Update manifest is missing the download URL or checksum.")
        log.info("Update available: %s -> %s", __version__, remote)
        return {"version": remote, "url": data["url"],
                "sha256": str(data["sha256"]).lower(), "notes": data.get("notes", "")}

    # -- download + verify -------------------------------------------
    def download(self, info: dict, progress_cb=None) -> Path:
        """Download the installer to a temp file and verify its SHA-256.
        Returns the path. Raises UpdateError on failure."""
        url, expected = info["url"], info["sha256"].lower()
        dest = Path(tempfile.gettempdir()) / f"Penguix-{info['version']}-setup.exe"
        sha = hashlib.sha256()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Penguix-Updater"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                read = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    read += len(chunk)
                    if progress_cb and total:
                        progress_cb(int(read * 100 / total))
        except Exception as exc:
            raise UpdateError(f"Download failed: {exc}") from exc
        if sha.hexdigest().lower() != expected:
            try:
                dest.unlink()
            except OSError:
                pass
            raise UpdateError("Downloaded file failed its checksum — discarded.")
        log.info("Update downloaded + verified: %s", dest)
        return dest

    def launch_installer(self, installer_path) -> None:
        """Start the installer and let the caller close the app so files can be
        replaced. The Inno Setup installer relaunches Penguix when done.

        IMPORTANT: PyInstaller onefile apps export _PYI*/_MEIPASS2 env vars that
        point at THIS app's temp extraction dir. If they leak into the installer
        (and on to the relaunched new app), the new onefile instance thinks it is
        a child process and tries to load its Python DLL from our old, now-deleted
        temp dir -> "Failed to load Python DLL". Launch with those vars stripped."""
        path = str(installer_path)
        env = os.environ.copy()
        for k in list(env):
            if k.startswith("_PYI") or k.startswith("_MEIPASS") or k == "_MEIPASS2":
                env.pop(k, None)
        if sys.platform.startswith("win"):
            subprocess.Popen([path], env=env, close_fds=True)
        else:  # dev/testing on non-Windows
            subprocess.Popen([path], env=env)
        log.info("Launched installer: %s", path)
