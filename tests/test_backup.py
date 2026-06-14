"""Headless tests for backup & restore."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.app_context import AppContext
from lubripos.services.product_service import ProductService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(data_root=tmp / "app"); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    bk = ctx.backup
    products = ProductService(ctx.db)

    print("\n[backup] create + validity + registry")
    pid = products.create({"name": "Original", "sale_price_minor": 1,
                           "purchase_price_minor": 1, "stock_qty": 5})
    path = bk.create_backup(backup_type="manual", user_id=1)
    check(Path(path).is_file() and Path(path).stat().st_size > 0, "backup file created")
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    check({"products", "sales", "users"}.issubset(names), "backup contains schema tables")
    reg = [b for b in bk.list_backups() if b["file_path"] == path]
    check(len(reg) == 1 and reg[0]["backup_type"] == "manual", "backup recorded in registry")

    print("\n[backup] custom folder honored")
    custom = tmp / "usb"
    bk.set_backup_dir(str(custom), user_id=1)
    check(Path(bk.get_backup_dir()) == custom, "custom backup dir saved + returned")
    cpath = bk.create_backup(backup_type="manual", user_id=1)
    check(Path(cpath).parent == custom, "backup written to custom folder")
    bk.set_backup_dir(None, user_id=1)
    check(Path(bk.get_backup_dir()) == cfg.backups_dir, "reset to default folder")

    print("\n[restore] round-trip reverts data")
    products.update(pid, {"name": "Changed After Backup"})
    check(products.get(pid)["name"] == "Changed After Backup", "data mutated")
    bk.restore_backup(path, user_id=1)
    check(products.get(pid)["name"] == "Original", "restore reverted data to backup state")

    print("\n[restore] validation rejects bad files")
    garbage = tmp / "garbage.db"
    garbage.write_bytes(b"this is not a database")
    try:
        bk.validate_backup(str(garbage)); check(False, "garbage should be rejected")
    except ValidationError:
        check(True, "non-sqlite file rejected")
    empty = tmp / "empty.db"
    sqlite3.connect(str(empty)).close()
    try:
        bk.validate_backup(str(empty)); check(False, "empty db should be rejected")
    except ValidationError:
        check(True, "valid sqlite but missing tables rejected")

    print("\n[auto] daily once + prune")
    # AppContext startup already ran one auto-backup today -> second call is a no-op
    check(bk.maybe_auto_backup() is None, "auto-backup skipped when already done today")
    ctx.db.execute("UPDATE app_meta SET value='2000-01-01' WHERE key='last_auto_backup'")
    check(bk.maybe_auto_backup() is not None, "auto-backup runs when due")
    # force many auto backups then prune
    for _ in range(16):
        bk.create_backup(backup_type="auto")
    bk._prune_auto_backups()
    n_auto = ctx.db.query_one("SELECT COUNT(*) n FROM backups WHERE backup_type='auto'")["n"]
    check(n_auto == 14, f"auto backups pruned to 14 (got {n_auto})")

    ctx.shutdown()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
