"""Headless tests: shop can oversell (sell warehouse stock), stock goes negative
and nets back up when distribution's purchase is entered. Also checks the v24
migration rebuild that removed the CHECK(stock_qty >= 0)."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.database.connection import Database
from lubripos.database.migrations import _migration_24_allow_negative_stock
from lubripos.services.product_service import ProductService
from lubripos.services.supplier_service import SupplierService
from lubripos.controllers.sale_controller import SaleController
from lubripos.controllers.purchase_controller import PurchaseController

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def _test_migration():
    print("\n[neg-stock] v24 migration rebuilds an old table (drops the CHECK)")
    p = Path(tempfile.mkdtemp()) / "old.db"
    db = Database(p)
    db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, "
               "name TEXT NOT NULL, stock_qty INTEGER NOT NULL DEFAULT 0 "
               "CHECK (stock_qty >= 0), barcode TEXT UNIQUE)")
    db.execute("CREATE INDEX idx_products_name ON products(name)")
    db.execute("INSERT INTO products (name, stock_qty, barcode) VALUES ('M5', 5, 'B1')")
    blocked = False
    try:
        db.execute("UPDATE products SET stock_qty = -3 WHERE id=1")
    except sqlite3.IntegrityError:
        blocked = True
    check(blocked, "negative blocked before migration")
    _migration_24_allow_negative_stock(db)
    row = db.query_one("SELECT name, stock_qty, barcode FROM products WHERE id=1")
    idx = db.query_one("SELECT 1 FROM sqlite_master WHERE type='index' "
                       "AND name='idx_products_name'")
    check(dict(row) == {"name": "M5", "stock_qty": 5, "barcode": "B1"},
          "data preserved through rebuild")
    check(idx is not None, "index preserved")
    db.execute("UPDATE products SET stock_qty = -3 WHERE id=1")
    check(db.query_one("SELECT stock_qty s FROM products WHERE id=1")["s"] == -3,
          "negative allowed after migration")
    db.close()


def _test_flow():
    print("\n[neg-stock] oversell -> negative -> purchase nets back up")
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ps = ProductService(ctx.db, ctx.audit)
    pid = ps.create({"name": "ZIC M5", "sale_price_minor": 150000,
                     "purchase_price_minor": 120000, "stock_qty": 0})
    sc = SaleController(ctx)

    ok, msg, _ = sc.checkout(lines=[{"product_id": pid, "qty": 1, "unit_price": 1500}])
    check(not ok, "a normal sale of an out-of-stock item is blocked")

    ok, _, _ = sc.checkout(lines=[{"product_id": pid, "qty": 1, "unit_price": 1500}],
                           allow_oversell=True)
    q = ctx.db.query_one("SELECT stock_qty q FROM products WHERE id=?", (pid,))["q"]
    check(ok and q == -1, "oversell sells the item and stock goes to -1")

    sup = SupplierService(ctx.db, ctx.audit).create({"name": "Distribution"})
    ok, _, _ = PurchaseController(ctx).create(
        supplier_id=sup, lines=[{"product_id": pid, "qty": 5, "unit_cost": 1200}],
        amount_paid=0)
    q = ctx.db.query_one("SELECT stock_qty q FROM products WHERE id=?", (pid,))["q"]
    check(ok and q == 4, "distribution's 5-unit purchase nets stock to 4 (-1 + 5)")
    ctx.shutdown()


def main() -> int:
    _test_migration()
    _test_flow()
    total, passed = len(_r), sum(_r)
    print(f"\n[neg-stock] {passed}/{total} checks passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
