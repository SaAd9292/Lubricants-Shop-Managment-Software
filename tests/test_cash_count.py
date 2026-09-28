"""Headless tests: end-of-day drawer count / reconciliation.

Expected == the running Cash in Hand; difference = counted - expected (over/
short); the count is recorded + audited but never changes Cash in Hand.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService
from lubripos.services.cash_service import CashService
from lubripos.controllers.sale_controller import SaleController
from lubripos.controllers.cash_controller import CashController

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ctx.company.update_tax({"tax_enabled": 0})
    ps = ProductService(ctx.db, ctx.audit)
    sc = SaleController(ctx)
    cc = CashController(ctx)
    cash = CashService(ctx.db)

    A = ps.create({"name": "Oil", "sale_price_minor": 100000,
                   "purchase_price_minor": 60000, "stock_qty": 100})
    # A big opening float + prior-day cash proves the drawer count ignores the
    # running total and only looks at TODAY'S takings.
    ctx.company.update_company({"cash_opening_minor": 500000,
                                "cash_opening_date": "2026-01-01"})
    sc.record_backdated_sale(lines=[{"product_id": A, "qty": 9, "unit_price": 1000}],
                             sale_date="2026-01-02", payment_method="Cash")   # old cash
    # today's movements: +3000 cash sale, -500 cash expense -> today's takings 2500
    sc.checkout(lines=[{"product_id": A, "qty": 3, "unit_price": 1000}],
                payment_method="Cash")
    from datetime import date
    ctx.db.execute("INSERT INTO expenses (category, amount_minor, expense_date, created_by) "
                   "VALUES ('Tea', 50000, ?, 1)", (date.today().isoformat() + " 10:00:00",))

    running_before = cash.current()

    print("\n[count] expected == TODAY'S takings, not the running total")
    check(cc.expected_cash() == 250000, "expected = Rs 2,500 (today 3,000 in - 500 out)")
    check(running_before > 250000, "running total is much larger (float + old cash)")
    check(cc.expected_cash() == cash.todays_takings(), "controller uses todays_takings()")

    print("\n[count] a matching count is balanced")
    ok, msg, data = cc.record_count(2500, notes="evening")
    check(ok, f"recorded ({msg})")
    check(data["difference_minor"] == 0, "counted 2,500 == today's takings -> difference 0")

    print("\n[count] a short count shows a negative difference")
    ok, _, short = cc.record_count(2000)
    check(short["expected_minor"] == 250000, "expected snapshot stored")
    check(short["difference_minor"] == -50000, "counted 2,000 -> SHORT by Rs 500")

    print("\n[count] an over count shows a positive difference")
    ok, _, over = cc.record_count(2700)
    check(over["difference_minor"] == 20000, "counted 2,700 -> OVER by Rs 200")

    print("\n[count] the count does NOT change cash in hand")
    check(cash.current() == running_before, "total cash in hand unchanged by counting")

    print("\n[count] persisted + audited")
    n = ctx.db.query_one("SELECT COUNT(*) n FROM cash_counts")["n"]
    check(n == 3, "3 counts recorded")
    audit = ctx.db.query_one(
        "SELECT COUNT(*) n FROM audit_logs WHERE action='CASH_COUNT'")["n"]
    check(audit == 3, "each count audited")
    last = cc.last_count()
    check(last and last["difference_minor"] == 20000, "last_count returns the latest")

    print("\n[count] a count for a PAST date uses that day's takings")
    # 02 Jan had a Rs 9,000 cash sale (booked above); count that specific day.
    exp_jan2 = cc.expected_cash("2026-01-02")
    check(exp_jan2 == 900000, "02 Jan expected = Rs 9,000 (that day's cash sale)")
    ok, _, past = cc.record_count(9000, day="2026-01-02")
    check(past["count_date"] == "2026-01-02" and past["difference_minor"] == 0,
          "past-date count stored against its day, balanced")
    check(cc.expected_cash() != exp_jan2, "today's expected differs from 02 Jan's")

    print("\n[count] negative counted amount is rejected")
    ok, msg, _ = cc.record_count(-5)
    check(not ok, "negative counted cash rejected")

    total, passed = len(_r), sum(_r)
    print(f"\n[count] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
