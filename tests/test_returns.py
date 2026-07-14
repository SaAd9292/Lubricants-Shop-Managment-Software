"""Headless tests for returns/refunds: lookup, partial + full returns (ledger),
stock restore, over-return guard, and net-of-returns reporting."""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.product_service import ProductService
from lubripos.services.report_service import ReportService
from lubripos.services.sale_service import SaleService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    cfg = Config(data_root=Path(tempfile.mkdtemp())); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    today = date.today().isoformat()
    ps = ProductService(ctx.db)
    ss = SaleService(ctx.db)

    pid = ps.create({"name": "Oil", "sale_price_minor": 10000,
                     "purchase_price_minor": 6000, "stock_qty": 10})
    sale = ss.create_sale(items=[{"product_id": pid, "qty": 5}], cashier_id=1,
                          cashier_name="Saad", payment_method="Cash")
    inv = sale["invoice_no"]
    item_id = ss.get_sale(sale["id"])["items"][0]["id"]

    print("\n[returns] lookup + partial return")
    check(ss.get_by_invoice(inv)["invoice_no"] == inv, "get_by_invoice finds the sale")
    check(ss.get_by_invoice("INV-NOPE") is None, "unknown invoice -> None")
    check(ps.get(pid)["stock_qty"] == 5, "stock 5 after selling 5")
    res = ss.create_return(sale["id"], [{"sale_item_id": item_id, "qty": 2}])
    check(res["refund_minor"] == 20000, "partial refund = 2 x 10000")
    check(ps.get(pid)["stock_qty"] == 7, "2 returned to stock -> 7")
    check(ss.get_sale(sale["id"])["items"][0]["returned_qty"] == 2, "returned_qty tracked")

    print("\n[returns] over-return guard")
    try:
        ss.create_return(sale["id"], [{"sale_item_id": item_id, "qty": 4}])
        check(False, "over-return should raise")
    except ValidationError:
        check(True, "cannot return more than remaining")

    print("\n[returns] day-close nets refunds out")
    dsr = ReportService(ctx.db).daily_sales(today)
    sm = {s["label"]: s["value"] for s in dsr["summary"]}
    # gross 5x10000=50000, refunds 20000, expenses 0 -> net 30000
    check(sm["Gross sales"] == 50000 and sm["Refunds"] == 20000 and sm["Net"] == 30000,
          "day-close: gross 50000, refunds 20000, net 30000")
    rsec = {s["name"]: s for s in dsr["sections"]}["Returns"]
    check(rsec["total"] == 20000 and len(rsec["rows"]) == 1, "day-close Returns section shows the refund")

    print("\n[returns] profit is net of returned margin")
    prof = ReportService(ctx.db).profit(today, today)
    pm = {s["label"]: s["value"] for s in prof["summary"]}
    # gross profit 5x(10000-6000)=20000; returned margin 2x4000=8000 -> net 12000
    check(pm["Refunds (returns)"] == 20000, "profit shows refunds")
    check(pm["Net profit (after returns)"] == 12000, "net profit nets the returned margin")

    print("\n[returns] full return restores all stock")
    ss.create_return(sale["id"], [{"sale_item_id": item_id, "qty": 3}])
    check(ps.get(pid)["stock_qty"] == 10, "all 5 returned -> stock back to 10")

    ctx.shutdown()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
