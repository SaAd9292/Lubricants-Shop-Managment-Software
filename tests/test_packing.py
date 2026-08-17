"""Headless tests: structured packing fields + selling a carton."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.controllers.sale_controller import SaleController
from lubripos.core.exceptions import ValidationError
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    ps = ProductService(ctx.db, ctx.audit)

    print("\n[packing] schema has the new columns")
    cols = {r["name"] for r in ctx.db.query("PRAGMA table_info(products)")}
    check({"series", "pack_size", "units_per_carton"} <= cols,
          "series/pack_size/units_per_carton present")

    print("\n[packing] create + read structured packing")
    pid = ps.create({"name": "ZIC TOP 0W-40 1L", "series": "Platinum",
                     "pack_size": "1 L", "units_per_carton": 12,
                     "purchase_price_minor": 278291, "sale_price_minor": 315191})
    p = ps.get(pid)
    check(p["series"] == "Platinum" and p["pack_size"] == "1 L" and p["units_per_carton"] == 12,
          "packing round-trips")

    print("\n[packing] units_per_carton validation")
    try:
        ps.create({"name": "Bad UPC", "units_per_carton": 0})
        check(False, "units_per_carton 0 should raise")
    except ValidationError:
        check(True, "units_per_carton 0 rejected")
    pid2 = ps.create({"name": "Default UPC"})
    check(ps.get(pid2)["units_per_carton"] == 1, "units_per_carton defaults to 1")

    print("\n[carton] selling a carton = units_per_carton bottles at the bottle price")
    p4 = ps.create({"name": "ZIC TOP 0W-40 4L", "units_per_carton": 4, "stock_qty": 10,
                    "purchase_price_minor": 1113163, "sale_price_minor": 1260763})
    prod = ps.get(p4)
    current_session.login(CurrentUser(id=1, username="admin", full_name="A", role="admin"))
    sc = SaleController(ctx)
    ok, _, summ = sc.checkout(
        lines=[{"product_id": p4, "qty": prod["units_per_carton"],
                "unit_price": prod["sale_price_minor"] / 100}],
        payment_method="Cash")
    check(ok, "carton sale (qty=4) checks out")
    check(ps.get(p4)["stock_qty"] == 10 - prod["units_per_carton"],
          "stock reduced by a full carton (4 bottles)")
    check(summ["grand_total_minor"] == prod["sale_price_minor"] * prod["units_per_carton"],
          "carton total = bottle price x units/carton (no tax configured)")

    total, passed = len(_r), sum(_r)
    print(f"\n[packing] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
