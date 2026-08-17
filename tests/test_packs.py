"""Headless tests: carton/piece helpers + Stock Report dual valuation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.packs import fmt_packs, name_with_pack, split_packs
from lubripos.services.product_service import ProductService
from lubripos.services.purchase_service import PurchaseService
from lubripos.services.report_service import ReportService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    print("\n[packs] split_packs / fmt_packs")
    check(split_packs(19, 6) == (3, 1), "19 @ 6/ctn = (3 ctn, 1 loose)")
    check(split_packs(48, 12) == (4, 0), "48 @ 12/ctn = (4 ctn, 0 loose)")
    check(split_packs(5, 1) == (0, 5), "upc 1 -> all loose")
    check(split_packs(0, 12) == (0, 0), "zero stock")
    check(fmt_packs(19, 6) == "3 ctn + 1 pc", "fmt 3 ctn + 1 pc")
    check(fmt_packs(48, 12) == "4 ctn", "fmt whole cartons only")
    check(fmt_packs(9, 12) == "9 pc", "fmt loose only")
    check(fmt_packs(5, 1) == "5", "fmt loose/drum = plain number")

    print("\n[packs] name_with_pack folds pack size into the name")
    check(name_with_pack("S-oil 0W-20", "4 L") == "S-oil 0W-20 4L", "appends '4L' (space removed)")
    check(name_with_pack("S-oil 0W-20 4L", "4 L") == "S-oil 0W-20 4L", "idempotent — no double append")
    check(name_with_pack("ZIC X5 5W-30", "3.8 L") == "ZIC X5 5W-30 3.8L", "handles 3.8L")
    check(name_with_pack("DOT-3 500ML", "") == "DOT-3 500ML", "no pack -> name unchanged")
    check(name_with_pack("  Havoline  ", "1 L") == "Havoline 1L", "trims + appends")

    print("\n[packs] Stock Report: cartons/pieces + dual valuation")
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    ps = ProductService(ctx.db, ctx.audit)
    # matches old report row: ZIC X7 FE 5W-20 3L @ 6/ctn, 3 ctn + 1 pc = 19
    ps.create({"name": "ZIC X7 FE 5W-20 3L", "units_per_carton": 6, "stock_qty": 19,
               "purchase_price_minor": 673728, "sale_price_minor": 686441})
    ps.create({"name": "DOT-3 500ML", "units_per_carton": 1, "stock_qty": 5,
               "purchase_price_minor": 130850, "sale_price_minor": 150000})
    rep = ReportService(ctx.db).stock()
    labels = [c["label"] for c in rep["columns"]]
    check("Cartons" in labels and "Loose" in labels and "Pcs/CTR" in labels,
          "report has Pcs/CTR + Cartons + Loose columns")
    check("Value (cost)" in labels and "Value (sale)" in labels,
          "report has both cost and sale value columns")

    row = next(r for r in rep["rows"] if r["name"].startswith("ZIC X7 FE 5W-20 3L"))
    check(row["cartons"] == 3 and row["loose"] == 1, "row split = 3 ctn + 1 loose")
    check(row["value"] == 19 * 673728, "row value at cost = 19 x 6,737.28 = 128,008.32")
    check(row["sale_value"] == 19 * 686441, "row value at sale = 19 x sale price")

    summ = {s["label"]: s["value"] for s in rep["summary"]}
    check(summ["Total stock value (at cost)"] == 19 * 673728 + 5 * 130850,
          "total-at-cost sums both products")
    check(summ["Total stock value (at sale)"] == 19 * 686441 + 5 * 150000,
          "total-at-sale sums both products")

    print("\n[packs] buying by the carton adds the right piece count")
    # The purchase dialog converts '2 ctn' of a 12/ctn product to 24 pieces; the
    # service stores pieces. Verify 2 cartons -> +24 stock, shown as '2 ctn'.
    pid = ps.create({"name": "ZIC X9 5W-40 1L", "units_per_carton": 12, "stock_qty": 0,
                     "purchase_price_minor": 250175, "sale_price_minor": 250175})
    PurchaseService(ctx.db).create_purchase(
        supplier_id=None, items=[{"product_id": pid, "qty": 2 * 12,
                                  "unit_cost_minor": 250175}])
    after = ps.get(pid)["stock_qty"]
    check(after == 24, "2 cartons x 12 = 24 pieces in stock")
    check(fmt_packs(after, 12) == "2 ctn", "24 pcs displays as '2 ctn'")

    total, passed = len(_r), sum(_r)
    print(f"\n[packs] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
