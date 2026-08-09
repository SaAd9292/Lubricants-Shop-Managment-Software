"""Headless tests for the cash drawer (open/close, movements, variance)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core import permissions as perms
from lubripos.services.cash_drawer_service import CashDrawerService
from lubripos.services.customer_service import CustomerService
from lubripos.services.expense_service import ExpenseService
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(data_root=tmp); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    cd = CashDrawerService(ctx.db)
    ps = ProductService(ctx.db)
    ss = SaleService(ctx.db)
    cs = CustomerService(ctx.db)

    print("\n[cash] open + guards")
    sid = cd.open_session(500000)                     # Rs 5,000 float
    check(cd.current() and cd.current()["id"] == sid, "drawer opens; current() finds it")
    try:
        cd.open_session(1000); check(False, "second open is blocked")
    except Exception:
        check(True, "second open is blocked")

    print("\n[cash] cash-in / cash-out flows into expected")
    pid = ps.create({"name": "Oil", "sale_price_minor": 100000, "stock_qty": 50})
    ss.create_sale(items=[{"product_id": pid, "qty": 3}], cashier_id=1,
                   cashier_name="C", payment_method="Cash")      # +3,000 cash
    ss.create_sale(items=[{"product_id": pid, "qty": 2}], cashier_id=1,
                   cashier_name="C", payment_method="Bank")      # bank: ignored
    cid = cs.find_or_create("Debtor", "0300")
    ss.create_sale(items=[{"product_id": pid, "qty": 1}], cashier_id=1, cashier_name="C",
                   payment_method="Debt", customer_id=cid, customer_name="Debtor")
    cs.record_payment(cid, 200000, method="Cash")               # +2,000 repayment
    cs.record_payment(cid, 100000, method="Bank")               # bank repayment: ignored
    cd.add_movement(sid, "out", 50000, reason="chai")           # -500 out
    cd.add_movement(sid, "in", 10000, reason="added change")    # +100 in

    exp = ExpenseService(ctx.db)
    # expense_date is stamped at MIDNIGHT today (exactly like the entry form) even
    # though the drawer opened later today — must still deduct (matched by when it
    # was recorded, not the accounting date).
    from datetime import date as _date
    midnight = _date.today().isoformat() + " 00:00:00"
    exp.create({"category": "Cleaning", "amount_minor": 30000, "expense_date": midnight,
                "payment_method": "Cash"}, user_id=1)           # -300 cash expense
    exp.create({"category": "Rent", "amount_minor": 500000, "expense_date": midnight,
                "payment_method": "Bank"}, user_id=1)           # bank: ignored

    t = cd.totals(cd.get(sid))
    check(t["cash_sales"] == 300000, "only CASH sales counted (3,000)")
    check(t["cash_repay"] == 200000, "only CASH repayments counted (2,000)")
    check(t["cash_expenses"] == 30000, "only CASH expenses deducted (300); bank ignored")
    check(t["paid_out"] == 50000 and t["paid_in"] == 10000, "movements summed")
    # 5000 + 3000 + 2000 + 100 - 0 - 300 - 500 = 9,300
    check(t["expected"] == 930000, "expected cash = 9,300 (cash expense deducted)")

    print("\n[cash] movements list")
    check(len(cd.movements(sid)) == 2, "two movements recorded")

    print("\n[cash] close + variance")
    res = cd.close_session(sid, 920000, note="Rs100 short")     # counted 9,200
    check(res["status"] == "closed", "session marked closed")
    check(res["expected_cash_minor"] == 930000, "expected snapshotted (9,300)")
    check(res["variance_minor"] == -10000, "variance = -100 (short)")
    check(cd.current() is None, "no open drawer after close")
    try:
        cd.add_movement(sid, "out", 100); check(False, "cannot move cash on a closed drawer")
    except Exception:
        check(True, "cannot move cash on a closed drawer")

    print("\n[cash] counted == expected -> variance 0")
    s2 = cd.open_session(0)
    exp = cd.totals(cd.get(s2))["expected"]
    r2 = cd.close_session(s2, exp)          # count exactly the expected amount
    check(r2["variance_minor"] == 0, "counting the expected amount gives zero variance")

    print("\n[cash] permission registered for cashiers")
    check("cashdrawer" in perms.SCREEN_KEYS, "cashdrawer is a grantable screen")
    check("cashdrawer" in perms.DEFAULT_CASHIER, "new cashiers get cashdrawer by default")

    ctx.shutdown()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
