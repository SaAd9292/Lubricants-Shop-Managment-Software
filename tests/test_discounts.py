"""Headless tests: per-line + whole-bill discounts on sales and purchases,
and profit reported net of both discount levels."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService
from lubripos.services.supplier_service import SupplierService
from lubripos.services.dashboard_service import DashboardService
from lubripos.services.payable_service import PayableService
from lubripos.controllers.sale_controller import SaleController
from lubripos.controllers.purchase_controller import PurchaseController

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ctx.company.update_tax({"tax_enabled": 0})     # clean math, no tax
    ps = ProductService(ctx.db, ctx.audit)
    sc = SaleController(ctx)
    A = ps.create({"name": "A", "sale_price_minor": 100000,
                   "purchase_price_minor": 60000, "stock_qty": 100})
    B = ps.create({"name": "B", "sale_price_minor": 50000,
                   "purchase_price_minor": 30000, "stock_qty": 100})

    print("\n[discounts] sale: per-line + whole-bill")
    # A: 2 x 1000, line disc 100 -> 1900 ; B: 3 x 500 -> 1500 ; subtotal 3400
    # bill disc 400 -> grand 3000
    ok, msg, s = sc.checkout(
        lines=[{"product_id": A, "qty": 2, "unit_price": 1000, "discount": 100},
               {"product_id": B, "qty": 3, "unit_price": 500}], discount=400)
    check(ok and s["subtotal_minor"] == 340000, "subtotal is net of line discounts")
    check(s["discount_minor"] == 40000, "bill discount stored")
    check(s["grand_total_minor"] == 300000, "grand = subtotal - bill discount")
    rows = ctx.db.query(
        "SELECT product_name, discount_minor, line_total_minor FROM sale_items "
        "WHERE sale_id=? ORDER BY id", (s["id"],))
    check(rows[0]["discount_minor"] == 10000 and rows[0]["line_total_minor"] == 190000,
          "line discount stored + line total is net of it")

    print("\n[discounts] profit is net of BOTH discount levels")
    # A margin 1900-1200=700 ; B margin 1500-900=600 ; line margins 1300 ; -400 bill = 900
    prof = DashboardService(ctx.db).summary("today")["today_profit_minor"]
    check(prof == 90000, "dashboard profit nets line + bill discounts (Rs 900.00)")

    print("\n[discounts] purchase: per-line + whole-bill")
    sup = SupplierService(ctx.db, ctx.audit).create({"name": "Dist"})
    pc = PurchaseController(ctx)
    # A: 5 x 600 line disc 200 -> 2800 ; B: 2 x 300 -> 600 ; subtotal 3400 ; bill 400 -> 3000
    ok, msg, pid = pc.create(
        supplier_id=sup, amount_paid=0, discount=400,
        lines=[{"product_id": A, "qty": 5, "unit_cost": 600, "discount": 200},
               {"product_id": B, "qty": 2, "unit_cost": 300}])
    prow = ctx.db.query_one(
        "SELECT discount_minor, total_minor FROM purchases WHERE id=?", (pid,))
    check(ok and prow["discount_minor"] == 40000 and prow["total_minor"] == 300000,
          "purchase total = subtotal - bill discount")
    pit = ctx.db.query(
        "SELECT discount_minor, line_total_minor FROM purchase_items "
        "WHERE purchase_id=? ORDER BY id", (pid,))
    check(pit[0]["discount_minor"] == 20000 and pit[0]["line_total_minor"] == 280000,
          "purchase line discount stored")
    bal = PayableService(ctx.db, ctx.audit).supplier_ledger(sup)["balance"]
    check(bal == 300000, "payable owed = discounted total")

    print("\n[discounts] product cost basis uses the DISCOUNTED unit cost")
    # A above: 5 x 600 with line discount 200 -> net 2800 -> eff unit 560 (56000 minor)
    a_cost = ps.get(A)["purchase_price_minor"]
    check(a_cost == 56000, "line discount lowered the product's unit cost (Rs 560)")
    # a bill-only discount must NOT change cost
    C = ps.create({"name": "C", "purchase_price_minor": 0, "sale_price_minor": 0,
                   "stock_qty": 0, "markup_bps": 0})
    pc.create(supplier_id=sup, amount_paid=0, discount=40,
              lines=[{"product_id": C, "qty": 4, "unit_cost": 50}])
    check(ps.get(C)["purchase_price_minor"] == 5000,
          "whole-bill discount does not change unit cost")

    print("\n[discounts] guards")
    ok, msg, _ = sc.checkout(
        lines=[{"product_id": A, "qty": 1, "unit_price": 1000, "discount": 2000}])
    check(not ok, "a line discount above the line total is rejected")

    total, passed = len(_r), sum(_r)
    print(f"\n[discounts] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
