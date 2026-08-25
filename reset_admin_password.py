"""Standalone Penguix admin-password reset — needs ONLY Python (no project source).

Resets a user's password (default: admin -> admin123) directly in the Penguix
database and forces a new password at next login. A .bak copy of the database is
made first, so it's safe.

CLOSE Penguix before running this.

Usage (from a Command Prompt / PowerShell):
    python reset_admin_password.py
    python reset_admin_password.py --db "C:\\Users\\<you>\\AppData\\Roaming\\Penguix\\lubripos.db"
    python reset_admin_password.py --user admin --password newtemp123
"""
import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path


def default_db() -> Path:
    home = os.environ.get("LUBRIPOS_HOME")
    if home:
        return Path(home).expanduser() / "lubripos.db"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "Penguix" / "lubripos.db"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Penguix" / "lubripos.db"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "Penguix" / "lubripos.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(default_db()), help="path to lubripos.db")
    ap.add_argument("--user", default="admin", help="username to reset")
    ap.add_argument("--password", default="admin123", help="temporary new password")
    a = ap.parse_args()

    db = Path(a.db)
    print("Database:", db)
    if not db.exists():
        print("  NOT FOUND. Open File Explorer, paste  %APPDATA%\\Penguix  in the address")
        print("  bar to find lubripos.db, then pass it with  --db \"<full path>\"")
        return 1

    shutil.copy2(str(db), str(db) + ".bak")   # safety backup first
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", a.password.encode("utf-8"), salt, 240_000)
    conn = sqlite3.connect(str(db))
    cur = conn.execute(
        "UPDATE users SET password_hash=?, password_salt=?, pwd_iterations=?, "
        "must_change_pw=1, is_active=1 WHERE username=? COLLATE NOCASE",
        (dk.hex(), salt.hex(), 240_000, a.user))
    conn.commit()
    conn.close()

    if cur.rowcount:
        print(f"OK — log in as '{a.user}' / '{a.password}' (you'll be asked to set a new one).")
        print("A backup of the old database was saved at:", str(db) + ".bak")
        return 0
    print(f"No user named '{a.user}' was found. Nothing changed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
