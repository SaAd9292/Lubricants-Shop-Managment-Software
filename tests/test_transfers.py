"""Headless tests for money transfers between cash and bank/wallet accounts.

Covers: derived account balances, cash-side folding into CashService, the DSR
'Account transfers' section + cash-drawer lines, reverse self-correction, and
validation (amount > 0, can't move to the same place).
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.cash_service import CashService
from lubripos.services.payment_account_service import PaymentAccountService
from lubripos.services.product_service import ProductService
from lubripos.services.report_service import ReportService
from lubripos.services.sale_service import SaleService
from lubripos.services.transfer_service import TransferService

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
    ts = TransferService(ctx.db, ctx.audit)
    cash = CashService(ctx.db)

    ep = pa.create({"method": "EasyPaisa", "name": "Shop EP"})

    # give EP a balance: a 30,000 sale paid into EasyPaisa (no cash involved)
    pid = ProductService(ctx.db).create({"name": "Oil", "sale_price_minor": 3_000_000,
                                          "purchase_price_minor": 2_000_000, "stock_qty": 5})
    SaleService(ctx.db).create_sale(
        items=[{"product_id": pid, "qty": 1}], cashier_id=1, cashier_name="Saad",
        payment_method="EasyPaisa", payment_account_id=ep)

    print("\n[xfer] starting balances")
    bal = {b["id"]: b["balance"] for b in ts.account_balances()}
    check(bal.get(ep) == 3_000_000, "EP balance = 30,000 from the EP sale")
    check(cash.balance_as_of(today) == 0, "cash still 0 (EP sale isn't cash)")

    print("\n[xfer] validation")
    for kw, why in (
        (dict(from_account_id=ep, to_account_id=None, amount_minor=0), "zero amount"),
        (dict(from_account_id=None, to_account_id=None, amount_minor=100), "cash→cash"),
        (dict(from_account_id=ep, to_account_id=ep, amount_minor=100), "same account"),
    ):
        try:
            ts.create_transfer(**kw, user_id=1); check(False, f"{why} allowed")
        except ValidationError:
            check(True, f"{why} rejected")
    try:
        ts.create_transfer(from_account_id=9999, to_account_id=None,
                           amount_minor=100, user_id=1)
        check(False, "unknown account allowed")
    except Exception:
        check(True, "unknown account rejected")

    print("\n[xfer] sweep 20,000 EP → cash")
    tid = ts.create_transfer(from_account_id=ep, to_account_id=None,
                             amount_minor=2_000_000, transfer_date=today, user_id=1)
    bal = {b["id"]: b["balance"] for b in ts.account_balances()}
    check(bal.get(ep) == 1_000_000, "EP down to 10,000")
    check(cash.balance_as_of(today) == 2_000_000, "cash up to 20,000")
    recon = cash.reconciliation(today)
    check(recon.get("transfers_in") == 2_000_000, "reconciliation transfers_in = 20,000")
    check(recon.get("transfers_out") == 0, "reconciliation transfers_out = 0")

    print("\n[xfer] DSR shows the transfer")
    dsr = ReportService(ctx.db).daily_sales(today)
    sec = [s for s in dsr["sections"]
           if s["name"].startswith("Account transfers")][0]
    check(sec["total"] == 2_000_000 and len(sec["rows"]) == 1,
          "Account transfers section lists the sweep")
    check(sec["rows"][0]["from_name"] == "Shop EP"
          and sec["rows"][0]["to_name"] == "Cash", "from EP → to Cash")
    drawer = [s for s in dsr["sections"] if s["name"] == "Cash drawer"][0]
    items = {r["item"]: r["amount"] for r in drawer["rows"]}
    check(any("Transfers into cash" in k for k in items), "cash drawer shows transfer-in line")

    print("\n[xfer] move 5,000 cash → EP (both directions)")
    ts.create_transfer(from_account_id=None, to_account_id=ep,
                       amount_minor=500_000, transfer_date=today, user_id=1)
    bal = {b["id"]: b["balance"] for b in ts.account_balances()}
    check(bal.get(ep) == 1_500_000, "EP back to 15,000")
    check(cash.balance_as_of(today) == 1_500_000, "cash down to 15,000")
    r2 = cash.reconciliation(today)
    check(r2.get("transfers_out") == 500_000, "reconciliation transfers_out = 5,000")

    print("\n[xfer] list + reverse self-corrects")
    hist = ts.list_transfers()
    check(hist["total"] == 2_500_000 and len(hist["rows"]) == 2, "history lists both moves")
    ts.reverse_transfer(tid, user_id=1)
    bal = {b["id"]: b["balance"] for b in ts.account_balances()}
    # after reversing the 20k EP→cash: EP +20k (=35k... minus the 5k cash→EP add = ...)
    # EP = 30,000(sale) + 5,000(cash→EP) - 0(the EP→cash sweep is gone) = 35,000
    check(bal.get(ep) == 3_500_000, "reversing the sweep restores EP (now 35,000)")
    check(cash.balance_as_of(today) == -500_000,
          "cash reflects only the remaining cash→EP move (−5,000)")

    ctx.shutdown()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
