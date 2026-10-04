"""Headless tests for partial (part-cash, part-udhaar) payment.

A credit sale where the customer pays PART now: the bill goes on their tab in
full, the paid part is recorded as a payment against it, so the balance = total
minus paid, and the paid part hits cash only when its method is cash.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService
from lubripos.services.customer_service import CustomerService
from lubripos.services.cash_service import CashService

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
    ss = SaleService(ctx.db, ctx.audit)
    cs = CustomerService(ctx.db, ctx.audit)
    cash = CashService(ctx.db)
    A = ps.create({"name": "Oil", "sale_price_minor": 300000,
                   "purchase_price_minor": 200000, "stock_qty": 100})

    def sell(cid, paid, method):
        return ss.create_sale(
            items=[{"product_id": A, "qty": 1, "unit_price_minor": 300000}],
            cashier_id=1, cashier_name="A", payment_method="Debt",
            customer_id=cid, customer_name="C", down_payment_minor=paid,
            down_payment_method=method, user_id=1)

    print("\n[partial] 3000 bill, pay 1500 cash -> owes 1500, till +1500")
    c1 = cs.create({"name": "C1"}); c1 = c1["id"] if isinstance(c1, dict) else c1
    before = cash.current()
    sell(c1, 150000, "Cash")
    check(cs.balance_owed(c1) == 150000, "customer owes the unpaid Rs 1,500")
    check(cash.current() - before == 150000, "cash in hand rises by the Rs 1,500 paid")

    print("\n[partial] 3000 bill, pay 1500 BANK -> owes 1500, till unchanged")
    c2 = cs.create({"name": "C2"}); c2 = c2["id"] if isinstance(c2, dict) else c2
    before = cash.current()
    sell(c2, 150000, "Bank")
    check(cs.balance_owed(c2) == 150000, "customer owes the unpaid Rs 1,500")
    check(cash.current() - before == 0, "bank down-payment does NOT touch the till")

    print("\n[partial] pay 0 -> full udhaar (unchanged behaviour)")
    c3 = cs.create({"name": "C3"}); c3 = c3["id"] if isinstance(c3, dict) else c3
    before = cash.current()
    sell(c3, 0, "Cash")
    check(cs.balance_owed(c3) == 300000, "full 3000 on the tab when nothing paid")
    check(cash.current() - before == 0, "no cash movement on a full-credit sale")

    print("\n[partial] overpay guard")
    c4 = cs.create({"name": "C4"}); c4 = c4["id"] if isinstance(c4, dict) else c4
    try:
        sell(c4, 400000, "Cash")
        check(False, "paying more than the bill should raise")
    except ValidationError:
        check(True, "cannot pay more now than the bill total")

    total, passed = len(_r), sum(_r)
    print(f"\n[partial] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
