"""Headless tests: the running, carry-over Cash in Hand.

The drawer starts from an opening float and moves with every cash event; the
balance carries from one day to the next (closing of day D == opening of D+1).
Only cash-method movements count; bank/wallet ones don't touch the till.
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
from lubripos.services.supplier_service import SupplierService
from lubripos.services.cash_service import CashService
from lubripos.services.report_service import ReportService
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
    ctx.company.update_tax({"tax_enabled": 0})
    ps = ProductService(ctx.db, ctx.audit)
    sc = SaleController(ctx)
    pc = PurchaseController(ctx)
    cash = CashService(ctx.db)
    mu = ctx.company.get_company().get("currency_minor_units", 100)

    D1, D2, D3 = "2026-01-10", "2026-01-11", "2026-01-12"
    A = ps.create({"name": "Oil", "sale_price_minor": 100000,
                   "purchase_price_minor": 60000, "stock_qty": 100})

    print("\n[cash] opening float sets the starting balance")
    ctx.company.update_company({"cash_opening_minor": 500000,   # Rs 5,000 float
                                "cash_opening_date": D1})
    check(cash.balance_as_of(D1) == 500000, "balance = opening float before any movement")

    print("\n[cash] day 1: cash sale in, cash expense out")
    sc.record_backdated_sale(lines=[{"product_id": A, "qty": 3, "unit_price": 1000}],
                             sale_date=D1, payment_method="Cash")   # +3000
    ctx.db.execute("INSERT INTO expenses (category, amount_minor, expense_date, created_by) "
                   "VALUES ('Rent', 200000, ?, 1)", (D1 + " 10:00:00",))  # -2000
    # 5000 + 3000 - 2000 = 6000
    check(cash.balance_as_of(D1) == 600000, "cash sale adds, expense subtracts (Rs 6,000)")

    print("\n[cash] a BANK sale does not touch the drawer")
    sc.record_backdated_sale(lines=[{"product_id": A, "qty": 2, "unit_price": 1000}],
                             sale_date=D1, payment_method="Bank")
    check(cash.balance_as_of(D1) == 600000, "bank sale left cash unchanged")

    print("\n[cash] day 2: balance carries over, purchase paid in cash goes out")
    # opening of D2 == closing of D1
    recon2_before = cash.reconciliation(D2)
    check(recon2_before["opening"] == 600000, "D2 opens at D1's closing (Rs 6,000)")
    sup = SupplierService(ctx.db, ctx.audit).create({"name": "Dist"})
    # purchase Rs 4,000, pay Rs 2,500 cash now (rest payable)
    pc.create(supplier_id=sup, amount_paid=2500, purchase_date=D2,
              lines=[{"product_id": A, "qty": 10, "unit_cost": 400}])
    # 6000 - 2500 = 3500
    check(cash.balance_as_of(D2) == 350000, "cash purchase payment leaves the till (Rs 3,500)")

    print("\n[cash] day 3: cash refund out, closing carries")
    # Returns stamp 'today', so to test on a fixed date insert a dated cash refund.
    ret = ctx.db.execute(
        "INSERT INTO sale_returns (sale_id, refund_minor, method, return_date, created_by) "
        "VALUES (NULL, 90000, 'Cash', ?, 1)", (D3 + " 12:00:00",))
    rid = ret.lastrowid
    ctx.db.execute(
        "INSERT INTO sale_return_items (return_id, sale_item_id, product_id, "
        "product_name, qty, unit_price_minor, line_total_minor) "
        "VALUES (?, NULL, ?, 'Oil', 1, 90000, 90000)",
        (rid, A))
    recon3 = cash.reconciliation(D3)
    check(recon3["refunds"] >= 90000, "cash refund recorded as cash-out on D3")
    # closing(D3) = opening(D3) - refund(90000 for the dated one) - (today's 900 return counts on today, not D3)
    check(recon3["closing"] == recon3["opening"] - recon3["cash_out"] + recon3["cash_in"],
          "D3 closing reconciles: opening + in - out")

    print("\n[cash] DSR exposes opening + closing that reconcile")
    rs = ReportService(ctx.db)
    dsr = rs.daily_sales(D2)
    summ = {s["label"]: s["value"] for s in dsr["summary"]}
    check(summ.get("Opening cash") == 600000, "DSR shows D2 opening = Rs 6,000")
    check(summ.get("Cash in hand") == 350000, "DSR shows D2 closing = Rs 3,500")
    sec = next((s for s in dsr["sections"] if s["name"] == "Cash drawer"), None)
    check(sec is not None and sec["total"] == 350000, "Cash drawer section totals to closing")

    print("\n[cash] no opening float set -> pure movement sum")
    ctx.company.update_company({"cash_opening_minor": 0, "cash_opening_date": None})
    b = cash.balance_as_of(D2)
    check(isinstance(b, int), "balance computes with no opening float set")

    total, passed = len(_r), sum(_r)
    print(f"\n[cash] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
