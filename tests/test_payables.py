"""Headless tests for supplier payables: balances, credit purchases, payments,
guards, and the per-supplier ledger."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.payable_service import PayableService
from lubripos.services.product_service import ProductService
from lubripos.services.purchase_service import PurchaseService
from lubripos.services.supplier_service import SupplierService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c)); print(f"  {PASS if c else FAIL}  {label}")


def _bal(pay, sid):
    return {r["id"]: r for r in pay.list_payables(only_outstanding=False)["rows"]}[sid]


def main() -> int:
    cfg = Config(data_root=Path(tempfile.mkdtemp())); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    ps = ProductService(ctx.db); sup_s = SupplierService(ctx.db)
    pu = PurchaseService(ctx.db); pay = PayableService(ctx.db)

    print("\n[payables] schema present")
    ver = ctx.db.query_one("SELECT value FROM app_meta WHERE key='schema_version'")["value"]
    check(int(ver) >= 8, f"schema_version >= 8 (got {ver})")
    check(any(r["name"] == "amount_paid_minor"
              for r in ctx.db.query("PRAGMA table_info(purchases)")),
          "purchases.amount_paid_minor exists")

    pid = ps.create({"name": "Oil", "sale_price_minor": 10000,
                     "purchase_price_minor": 6000, "stock_qty": 0})
    sid = sup_s.create({"name": "Khan Oil Store"})

    print("\n[payables] fully-paid purchase -> zero balance")
    pu.create_purchase(supplier_id=sid,
                       items=[{"product_id": pid, "qty": 10, "unit_cost_minor": 6000}])
    b = _bal(pay, sid)
    check(b["purchased"] == 60000 and b["paid"] == 60000 and b["balance"] == 0,
          "purchased 60000, paid in full, balance 0")

    print("\n[payables] credit purchase creates a payable")
    pu.create_purchase(supplier_id=sid,
                       items=[{"product_id": pid, "qty": 10, "unit_cost_minor": 4000}],
                       amount_paid_minor=15000)  # total 40000, paid 15000
    b = _bal(pay, sid)
    check(b["purchased"] == 100000 and b["paid"] == 75000 and b["balance"] == 25000,
          "balance owed 25000 after partial payment")

    print("\n[payables] recording a later payment reduces the balance")
    pay.record_payment(sid, 10000, method="Cash")
    check(_bal(pay, sid)["balance"] == 15000, "balance 15000 after paying 10000")
    check(pay.total_outstanding() == 15000, "total_outstanding = 15000")
    ids = [r["id"] for r in pay.list_payables(only_outstanding=True)["rows"]]
    check(sid in ids, "supplier appears in only-outstanding view")

    print("\n[payables] guards")
    try:
        pay.record_payment(sid, 0); check(False, "zero payment should raise")
    except ValidationError:
        check(True, "zero/negative payment rejected")
    try:
        pu.create_purchase(supplier_id=sid,
                           items=[{"product_id": pid, "qty": 1, "unit_cost_minor": 5000}],
                           amount_paid_minor=999999)
        check(False, "overpay-at-purchase should raise")
    except ValidationError:
        check(True, "amount paid cannot exceed total")
    try:
        pu.create_purchase(supplier_id=None,
                           items=[{"product_id": pid, "qty": 1, "unit_cost_minor": 5000}],
                           amount_paid_minor=0)
        check(False, "credit purchase without supplier should raise")
    except ValidationError:
        check(True, "credit purchase requires a supplier")

    print("\n[payables] supplier ledger")
    led = pay.supplier_ledger(sid)
    check(len(led["purchases"]) == 2, "ledger lists both purchases")
    check(len(led["payments"]) == 1, "ledger lists the payment")
    check(led["balance"] == 15000, "ledger balance 15000")

    print("\n[payables] edit + reverse a supplier payment")
    pay2 = pay.record_payment(sid, 5000, method="Cash", payment_date="2026-09-10")
    check(_bal(pay, sid)["balance"] == 10000, "balance 10000 after paying 5000")
    lp = pay.list_payments(date_from="2026-09-01", date_to="2026-09-30")
    check(len(lp["rows"]) == 1 and lp["rows"][0]["id"] == pay2,
          "payment listed with its id in the date range")
    pay.update_payment(pay2, amount_minor=8000, method="Bank")
    check(_bal(pay, sid)["balance"] == 7000, "amount edit (8000) lowers balance to 7000")
    check(pay.get_payment(pay2)["method"] == "Bank", "method edit (Bank) persisted")
    pay.reverse_payment(pay2)
    check(_bal(pay, sid)["balance"] == 15000, "reverse restores balance to 15000")
    check(len(pay.list_payments(date_from="2026-09-01", date_to="2026-09-30")["rows"]) == 0,
          "reversed payment no longer listed")

    ctx.shutdown()
    n = sum(_r); print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
