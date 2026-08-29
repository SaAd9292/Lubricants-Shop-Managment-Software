"""Headless tests: admin delete-purchase reverses stock + payable, safely."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService
from lubripos.services.supplier_service import SupplierService
from lubripos.services.payable_service import PayableService
from lubripos.controllers.purchase_controller import PurchaseController

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    ps = ProductService(ctx.db, ctx.audit)
    ss = SaleService(ctx.db, ctx.audit)
    pay = PayableService(ctx.db, ctx.audit)
    pid = ps.create({"name": "ZIC M5", "sale_price_minor": 150000,
                     "purchase_price_minor": 120000, "stock_qty": 0})
    sup = SupplierService(ctx.db, ctx.audit).create({"name": "ACME"})
    pc = PurchaseController(ctx)

    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ok, _, purch = pc.create(supplier_id=sup,
                             lines=[{"product_id": pid, "qty": 10, "unit_cost": 1200}],
                             amount_paid=0)
    check(ok, "admin created a credit purchase of 10")
    check(ctx.db.query_one("SELECT stock_qty s FROM products WHERE id=?", (pid,))["s"] == 10,
          "stock rose to 10")
    # unit cost 1200 -> 120000 minor; x10 units = 1,200,000 minor owed
    check(pay.supplier_ledger(sup)["balance"] == 120000 * 10,
          "supplier is owed the purchase total")

    print("\n[purchase-delete] guards")
    current_session.login(CurrentUser(id=2, username="c", full_name="C", role="cashier"))
    ok, msg, _ = pc.delete(purch)
    check(not ok, "cashier is refused")

    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ss.create_sale(items=[{"product_id": pid, "qty": 3}], cashier_id=1,
                   cashier_name="A", user_id=1)
    ok, msg, _ = pc.delete(purch)
    check(not ok and "already been sold" in msg,
          "blocked when some units were already sold")

    print("\n[purchase-delete] clean delete reverses everything")
    ps.adjust_stock(pid, 10, "undo test sale", user_id=1)   # put stock back
    ok, _, _ = pc.delete(purch)
    check(ok, "delete succeeds once stock is restored")
    check(ctx.db.query_one("SELECT COUNT(*) n FROM purchases WHERE id=?", (purch,))["n"] == 0,
          "purchase row is gone")
    check(ctx.db.query_one("SELECT COUNT(*) n FROM purchase_items WHERE purchase_id=?",
                           (purch,))["n"] == 0, "purchase items cascade-deleted")
    check(ctx.db.query_one("SELECT stock_qty s FROM products WHERE id=?", (pid,))["s"] == 0,
          "stock reversed (10 added -> removed)")
    check(pay.supplier_ledger(sup)["balance"] == 0, "supplier liability reversed")

    total, passed = len(_r), sum(_r)
    print(f"\n[purchase-delete] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
