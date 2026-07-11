"""Headless tests for named payment accounts (Bank/EasyPaisa/JazzCash)."""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.payment_account_service import PaymentAccountService
from lubripos.services.product_service import ProductService
from lubripos.services.report_service import ReportService
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
    today = date.today().isoformat()
    pa = PaymentAccountService(ctx.db)

    print("\n[pay] create + list + validation")
    jc = pa.create({"method": "JazzCash", "name": "Saad JazzCash", "account_no": "0300-1"})
    ep = pa.create({"method": "EasyPaisa", "name": "Shop EP"})
    check(len(pa.list_accounts()) == 2, "two accounts created")
    check(len(pa.list_accounts(method="JazzCash")) == 1, "filter by method")
    for bad in ({"method": "Nope", "name": "x"}, {"method": "Bank", "name": ""}):
        try:
            pa.create(bad); check(False, "invalid account allowed")
        except ValidationError:
            check(True, "invalid account rejected")

    print("\n[pay] deactivate hides from active list")
    pa.set_active(ep, False)
    check(len(pa.list_accounts(active_only=True)) == 1, "deactivated account hidden from POS list")
    pa.set_active(ep, True)

    print("\n[pay] sale snapshots the account")
    pid = ProductService(ctx.db).create({"name": "Oil", "sale_price_minor": 100000,
                                          "purchase_price_minor": 60000, "stock_qty": 5})
    ss = SaleService(ctx.db)
    s = ss.create_sale(items=[{"product_id": pid, "qty": 1}], cashier_id=1,
                       cashier_name="Saad", payment_method="JazzCash", payment_account_id=jc)
    row = dict(ctx.db.query_one(
        "SELECT payment_account_id, payment_account_name FROM sales WHERE id=?", (s["id"],)))
    check(row["payment_account_id"] == jc and row["payment_account_name"] == "Saad JazzCash",
          "sale stores account id + name snapshot")
    try:
        ss.create_sale(items=[{"product_id": pid, "qty": 1}], cashier_id=1, cashier_name="S",
                       payment_method="Bank", payment_account_id=9999)
        check(False, "unknown account id allowed")
    except ValidationError:
        check(True, "unknown account id rejected")

    print("\n[pay] delete keeps history (FK set null, name snapshot kept)")
    pa.delete(jc)
    row = dict(ctx.db.query_one(
        "SELECT payment_account_id, payment_account_name FROM sales WHERE id=?", (s["id"],)))
    check(row["payment_account_id"] is None and row["payment_account_name"] == "Saad JazzCash",
          "delete nulls the link but keeps the name on the sale")

    print("\n[pay] day-close money received is broken down by account")
    dsr = ReportService(ctx.db).daily_sales(today)
    mr = [x for x in dsr["sections"] if x["name"] == "Money received"][0]
    labels = [r["method"] for r in mr["rows"]]
    check(any("Saad JazzCash" in x for x in labels),
          "Money received lists the named account")

    ctx.shutdown()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
