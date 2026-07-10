"""Headless tests: markup-over-cost pricing and auto-reprice on purchase."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.money import apply_markup
from lubripos.services.product_service import ProductService
from lubripos.services.purchase_service import PurchaseService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def make_ctx() -> AppContext:
    return AppContext(Config(data_root=Path(tempfile.mkdtemp())))


def main() -> int:
    print("\n[pricing] apply_markup math")
    check(apply_markup(50000, 2000, 100) == 60000, "Rs500 +20% = Rs600")
    check(apply_markup(43700, 1800, 100) == 51600, "Rs437 +18% = Rs516 (nearest 1)")
    check(apply_markup(10000, 0, 100) == 10000, "0% markup -> cost unchanged")
    check(apply_markup(0, 2000, 100) == 0, "zero cost -> 0")
    check(apply_markup(33333, 5000, 1) == 49999 or apply_markup(33333, 5000, 1) == 50000,
          "round_to_minor=1 rounds to nearest minor unit")

    ctx = make_ctx()
    products = ProductService(ctx.db, ctx.audit)
    purchases = PurchaseService(ctx.db, ctx.audit)

    print("\n[pricing] purchase auto-reprices a marked-up product")
    pid = products.create({
        "name": "ZIC 5W-30 4L", "purchase_price_minor": 100000,
        "sale_price_minor": 120000, "markup_bps": 2000, "stock_qty": 0,
    })
    purchases.create_purchase(supplier_id=None, items=[
        {"product_id": pid, "qty": 5, "unit_cost_minor": 150000}])
    p = products.get(pid)
    check(p["purchase_price_minor"] == 150000, "cost updated to last purchase cost")
    check(p["sale_price_minor"] == 180000, "sale auto-repriced to cost+20% (Rs1800)")
    check(p["stock_qty"] == 5, "stock increased by purchased qty")

    print("\n[pricing] markup 0 leaves the manual sale price untouched")
    pid2 = products.create({
        "name": "Promo Grease", "purchase_price_minor": 50000,
        "sale_price_minor": 99999, "markup_bps": 0, "stock_qty": 0,
    })
    purchases.create_purchase(supplier_id=None, items=[
        {"product_id": pid2, "qty": 3, "unit_cost_minor": 60000}])
    p2 = products.get(pid2)
    check(p2["purchase_price_minor"] == 60000, "cost still updates when markup 0")
    check(p2["sale_price_minor"] == 99999, "manual sale price preserved (markup 0)")

    print("\n[pricing] negative markup rejected")
    try:
        products.create({"name": "Bad", "markup_bps": -5})
        check(False, "negative markup should raise")
    except Exception:
        check(True, "negative markup rejected")

    total, passed = len(_r), sum(_r)
    print(f"\n[pricing] {passed}/{total} checks passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
