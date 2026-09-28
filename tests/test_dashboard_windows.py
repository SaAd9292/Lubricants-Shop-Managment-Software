"""Headless tests: dashboard analytics over an arbitrary FROM–TO date range.

Totals cover [from, to] inclusive; deltas compare to the equal-length span
immediately before; the chart buckets by day for short ranges and by month for
long ones.
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
from lubripos.services.dashboard_service import DashboardService
from lubripos.controllers.sale_controller import SaleController

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def sale(sc, pid, qty, price, d):
    sc.record_backdated_sale(lines=[{"product_id": pid, "qty": qty, "unit_price": price}],
                             sale_date=d, payment_method="Cash")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ctx.company.update_tax({"tax_enabled": 0})
    ps = ProductService(ctx.db, ctx.audit)
    sc = SaleController(ctx)
    ds = DashboardService(ctx.db)
    A = ps.create({"name": "Oil", "sale_price_minor": 100000,
                   "purchase_price_minor": 60000, "stock_qty": 100000})

    sale(sc, A, 1, 1000, "2026-06-10")   # inside range
    sale(sc, A, 2, 1000, "2026-06-15")   # inside range
    sale(sc, A, 5, 1000, "2026-06-25")   # outside range (> to)
    sale(sc, A, 3, 1000, "2026-06-05")   # in the previous-span window

    print("\n[dash] range totals cover [from, to] inclusive")
    s = ds.summary("2026-06-10", "2026-06-20")
    check(s["today_sales_minor"] == 300000, "10–20 Jun total = Rs 3,000 (excludes 25th & 5th)")
    check(s["window_start"] == "2026-06-10" and s["window_end"] == "2026-06-20",
          "window echoes the from/to")

    print("\n[dash] inverted from/to is ordered safely")
    s2 = ds.summary("2026-06-20", "2026-06-10")
    check(s2["today_sales_minor"] == 300000, "swapped dates give the same total")

    print("\n[dash] single-day range")
    s3 = ds.summary("2026-06-15", "2026-06-15")
    check(s3["today_sales_minor"] == 200000, "just the 15th = Rs 2,000")

    print("\n[dash] deltas compare to the equal-length span just before")
    # range 10–20 Jun is 11 days; previous span = 30 May–09 Jun, which holds the
    # 05 Jun sale (Rs 3,000). Current 3,000 vs previous 3,000 -> 0%.
    d = ds.deltas("2026-06-10", "2026-06-20")
    check(d["label"] == "vs previous period", "delta label")
    check(abs((d["sales_pct"] or 0) - 0.0) < 0.01, "sales flat vs the prior 11 days")

    print("\n[dash] chart buckets: daily for short, monthly for long")
    cs = ds.chart_series("2026-06-10", "2026-06-20")
    check(len(cs) == 11 and cs[0]["date"] == "2026-06-10", "11 daily bars")
    cm = ds.chart_series("2026-01-01", "2026-12-31")
    check(len(cm) == 12 and cm[0]["label"].startswith("Jan"), "full year -> 12 monthly bars")

    print("\n[dash] window-scoped lists")
    lst = ds.sales_in_window("2026-06-25", "2026-06-25", 6)
    check(len(lst) == 1 and lst[0]["grand_total_minor"] == 500000,
          "sales list scoped to the 25th only")
    top = ds.top_sellers("2026-06-01", "2026-06-30", 5)
    check(top and top[0]["qty"] == 11, "June top seller = 11 units of Oil")

    total, passed = len(_r), sum(_r)
    print(f"\n[dash] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
