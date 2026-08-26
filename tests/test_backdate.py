"""Headless tests: back-dated bulk bill entry (Admin Panel > Back-date Entry).

Covers: admin-only guard, real sale_date stamping, multi-line + discount totals,
paid-in-full recording, short-line flooring at 0 (never breaking the DB's
stock_qty >= 0 invariant), and that the live POS path still blocks oversell.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.core.exceptions import InsufficientStockError
from lubripos.services.product_service import ProductService
from lubripos.controllers.sale_controller import SaleController

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    ps = ProductService(ctx.db, ctx.audit)
    a = ps.create({"name": "ZIC M5 20W-50 4L", "sale_price_minor": 150000,
                   "purchase_price_minor": 120000, "stock_qty": 10})
    b = ps.create({"name": "Shell Helix 1L", "sale_price_minor": 90000,
                   "purchase_price_minor": 70000, "stock_qty": 2})
    sc = SaleController(ctx)

    print("\n[backdate] admin-only")
    current_session.login(CurrentUser(id=2, username="c", full_name="C", role="cashier"))
    ok, _, _ = sc.record_backdated_sale(
        lines=[{"product_id": a, "qty": 1, "unit_price": 1500}], sale_date="2026-07-05")
    check(not ok, "cashier is refused")

    print("\n[backdate] admin multi-line, discount, one short line, back-dated")
    current_session.login(CurrentUser(id=1, username="admin", full_name="A", role="admin"))
    ok, msg, s = sc.record_backdated_sale(
        lines=[{"product_id": a, "qty": 3, "unit_price": 1500},
               {"product_id": b, "qty": 5, "unit_price": 900}],
        sale_date="2026-07-05", discount=200)
    check(ok, f"bill saved ({msg})")
    # 3*150000 + 5*90000 = 900000 ; less 20000 discount = 880000
    check(s and s["grand_total_minor"] == 880000, "grand total = subtotal - discount")
    check(s and s["short_lines"] == ["Shell Helix 1L"], "short line reported")

    row = ctx.db.query_one(
        "SELECT sale_date, amount_paid_minor, status FROM sales WHERE id=?", (s["id"],))
    check(row["sale_date"].startswith("2026-07-05"), "stamped on the real bill date")
    check(row["amount_paid_minor"] == 880000, "recorded paid in full")
    check(row["status"] == "completed", "status completed")

    ra = ctx.db.query_one("SELECT stock_qty FROM products WHERE id=?", (a,))
    rb = ctx.db.query_one("SELECT stock_qty FROM products WHERE id=?", (b,))
    check(ra["stock_qty"] == 7, "in-stock line decremented normally (10 - 3)")
    check(rb["stock_qty"] == 0, "short line floored at 0, not negative")

    print("\n[backdate] live POS path is unchanged")
    try:
        sc.sales.create_sale(items=[{"product_id": a, "qty": 999}],
                             cashier_id=1, cashier_name="A", user_id=1)
        check(False, "live oversell should raise")
    except InsufficientStockError:
        check(True, "live sale still blocks oversell")

    r = ctx.db.query_one(
        "SELECT COUNT(*) n FROM sales WHERE date(sale_date)='2026-07-05' "
        "AND status='completed'")
    check(r["n"] == 1, "back-dated bill lands in reports for that day")

    print("\n[backdate] payment methods")
    ps.create({"name": "Grease 500g", "sale_price_minor": 40000,
               "purchase_price_minor": 30000, "stock_qty": 50})
    grease = ctx.db.query_one("SELECT id FROM products WHERE name='Grease 500g'")["id"]

    # Cash -> recorded paid in full
    ok, _, cash = sc.record_backdated_sale(
        lines=[{"product_id": grease, "qty": 2, "unit_price": 400}],
        sale_date="2026-07-10", payment_method="Cash")
    crow = ctx.db.query_one(
        "SELECT payment_method, amount_paid_minor, grand_total_minor "
        "FROM sales WHERE id=?", (cash["id"],))
    check(ok and crow["payment_method"] == "Cash"
          and crow["amount_paid_minor"] == crow["grand_total_minor"],
          "Cash bill recorded paid in full")

    # Credit (Debt) without a customer is refused
    ok, msg, _ = sc.record_backdated_sale(
        lines=[{"product_id": grease, "qty": 1, "unit_price": 400}],
        sale_date="2026-07-11", payment_method="Debt")
    check(not ok, f"credit bill without customer refused ({msg[:30]})")

    # Credit (Debt) with a customer -> unpaid, sits on the tab
    ok, _, debt = sc.record_backdated_sale(
        lines=[{"product_id": grease, "qty": 1, "unit_price": 400}],
        sale_date="2026-07-11", payment_method="Debt", customer_name="Ali Traders")
    drow = ctx.db.query_one(
        "SELECT payment_method, amount_paid_minor, customer_id FROM sales WHERE id=?",
        (debt["id"],))
    check(ok and drow["payment_method"] == "Debt"
          and drow["amount_paid_minor"] == 0 and drow["customer_id"] is not None,
          "Credit bill is unpaid and attached to a customer")

    print("\n[backdate] picking a saved customer by id attaches to that record")
    existing = drow["customer_id"]   # the "Ali Traders" customer created above
    ok, _, s2 = sc.record_backdated_sale(
        lines=[{"product_id": grease, "qty": 3, "unit_price": 400}],
        sale_date="2026-07-12", payment_method="Cash", customer_id=existing,
        customer_name="Ali Traders")
    row2 = ctx.db.query_one("SELECT customer_id FROM sales WHERE id=?", (s2["id"],))
    check(ok and row2["customer_id"] == existing,
          "picked customer_id is used directly (no duplicate customer created)")
    n = ctx.db.query_one(
        "SELECT COUNT(*) n FROM customers WHERE name='Ali Traders'")["n"]
    check(n == 1, "still exactly one 'Ali Traders' (no duplicate)")

    total, passed = len(_r), sum(_r)
    print(f"\n[backdate] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
