"""Headless tests: no-receipt (unlinked) returns.

A customer brings goods back with no receipt. The operator restores stock and
refunds an amount they decide (there's no sale to price against). The refund
method matters: only Cash refunds come out of cash-in-hand on the DSR.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService
from lubripos.services.report_service import ReportService
from lubripos.controllers.sale_controller import SaleController

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
    rs = ReportService(ctx.db)
    today = date.today().isoformat()

    A = ps.create({"name": "Widget", "sale_price_minor": 100000,
                   "purchase_price_minor": 60000, "stock_qty": 10})

    print("\n[noreceipt] cash refund restores stock and records the return")
    ok, msg, data = sc.create_no_receipt_return(
        lines=[{"product_id": A, "qty": 2, "refund": 1800}],
        method="Cash", notes="paper bill 42")
    check(ok, f"controller returned ok ({msg})")
    check(ps.get(A)["stock_qty"] == 12, "stock restored (10 -> 12)")
    check(data and data["refund_minor"] == 180000, "refund total is Rs 1800")
    row = ctx.db.query_one(
        "SELECT sale_id, method, refund_minor, notes FROM sale_returns WHERE id=?",
        (data["return_id"],))
    check(row["sale_id"] is None, "return is unlinked (sale_id NULL)")
    check(row["method"] == "Cash", "refund method stored")
    check(row["notes"] == "paper bill 42", "reason/note stored")
    it = ctx.db.query_one(
        "SELECT sale_item_id, product_id, qty, line_total_minor "
        "FROM sale_return_items WHERE return_id=?", (data["return_id"],))
    check(it["sale_item_id"] is None and it["product_id"] == A and it["qty"] == 2,
          "return item is unlinked, right product + qty")

    print("\n[noreceipt] a CASH refund lowers cash-in-hand on the DSR")
    # book a Rs 5000 cash sale today so cash-in-hand has a base
    sc.checkout(lines=[{"product_id": A, "qty": 5, "unit_price": 1000}],
                payment_method="Cash")
    dsr = rs.daily_sales(today)
    cash = _find_cash_in_hand(dsr)
    # cash sale 5000, minus the 1800 cash no-receipt refund = 3200
    check(cash == 320000, f"cash-in-hand nets the cash refund (got {cash})")

    print("\n[noreceipt] a NON-cash refund does NOT touch cash-in-hand")
    sc.create_no_receipt_return(
        lines=[{"product_id": A, "qty": 1, "refund": 900}], method="Bank")
    dsr2 = rs.daily_sales(today)
    cash2 = _find_cash_in_hand(dsr2)
    check(cash2 == 320000, f"bank refund left cash-in-hand unchanged (got {cash2})")
    check(ps.get(A)["stock_qty"] == 8, "stock updated across sale + returns (12-5+1=8)")

    print("\n[noreceipt] guards")
    ok, msg, _ = sc.create_no_receipt_return(
        lines=[{"product_id": A, "qty": 1, "refund": -5}], method="Cash")
    check(not ok, "a negative refund is rejected")

    total, passed = len(_r), sum(_r)
    print(f"\n[noreceipt] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


def _find_cash_in_hand(report) -> int | None:
    """Pull the 'Cash in hand' figure out of the day-close DSR structure,
    whatever shape report_service returns (rows/sections/summary)."""
    def scan(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and "cash_in_hand" in k.lower():
                    return v
                found = scan(v)
                if found is not None:
                    return found
            # label/value pair rows
            label = str(obj.get("label", "")).lower()
            if "cash in hand" in label:
                for key in ("value_minor", "amount_minor", "value", "amount"):
                    if key in obj:
                        return obj[key]
        elif isinstance(obj, (list, tuple)):
            for el in obj:
                found = scan(el)
                if found is not None:
                    return found
        return None
    return scan(report)


if __name__ == "__main__":
    sys.exit(main())
