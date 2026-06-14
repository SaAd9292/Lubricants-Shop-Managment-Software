"""Headless tests for the sales/checkout service (no Qt)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.config import Config
from lubripos.core.exceptions import InsufficientStockError, ValidationError
from lubripos.database.connection import Database
from lubripos.database.db import init_database
from lubripos.services.company_service import CompanyService
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def make_db(tmp):
    cfg = Config(data_root=tmp); cfg.ensure_dirs()
    db = Database(cfg.db_path); init_database(db)
    return db


def run(db):
    company = CompanyService(db)
    products = ProductService(db)
    sales = SaleService(db)

    p1 = products.create({"name": "ZIC X7 4L", "sale_price_minor": 30000,
                          "purchase_price_minor": 25000, "stock_qty": 20})
    p2 = products.create({"name": "Shell HX7 4L", "sale_price_minor": 27000,
                          "purchase_price_minor": 22000, "stock_qty": 10})

    print("\n[sale] no tax: totals + stock decrement")
    company.update_tax({"tax_enabled": 0, "tax_rate_bps": 0})
    s = sales.create_sale(items=[{"product_id": p1, "qty": 2}, {"product_id": p2, "qty": 1}],
                          cashier_id=1, cashier_name="Cashier")
    check(s["subtotal_minor"] == 2*30000 + 27000, "subtotal correct")
    check(s["tax_minor"] == 0 and s["grand_total_minor"] == s["subtotal_minor"], "no tax applied")
    check(products.get(p1)["stock_qty"] == 18, "p1 stock 20 -> 18")
    check(products.get(p2)["stock_qty"] == 9, "p2 stock 10 -> 9")
    check(s["invoice_no"] == "INV-000001", "first invoice number sequential")

    print("\n[sale] sequential invoice numbers")
    s2 = sales.create_sale(items=[{"product_id": p1, "qty": 1}], cashier_id=1, cashier_name="C")
    check(s2["invoice_no"] == "INV-000002", "second invoice increments")

    print("\n[sale] exclusive tax 17% + discount")
    company.update_tax({"tax_enabled": 1, "tax_rate_bps": 1700, "tax_inclusive": 0})
    # 4 x 30000 = 120000 subtotal, discount 20000 -> net 100000, tax 17000, grand 117000
    s3 = sales.create_sale(items=[{"product_id": p1, "qty": 4}], cashier_id=1,
                           cashier_name="C", discount_minor=20000)
    check(s3["subtotal_minor"] == 120000, "subtotal before discount")
    check(s3["tax_minor"] == 17000, "tax = 17% of net (100000) = 17000")
    check(s3["grand_total_minor"] == 117000, "grand total = net + tax")

    print("\n[sale] inclusive tax")
    company.update_tax({"tax_enabled": 1, "tax_rate_bps": 1700, "tax_inclusive": 1})
    s4 = sales.create_sale(items=[{"product_id": p2, "qty": 1}], cashier_id=1, cashier_name="C")
    # net = 27000, inclusive: grand stays 27000, tax backed out
    check(s4["grand_total_minor"] == 27000, "inclusive: grand == net (tax embedded)")
    check(s4["tax_minor"] > 0 and s4["tax_minor"] < 27000, "inclusive: tax backed out for reporting")

    print("\n[sale] oversell blocked + rolled back")
    company.update_tax({"tax_enabled": 0})
    before = products.get(p2)["stock_qty"]
    cnt_before = sales.list_sales()["total"]
    try:
        sales.create_sale(items=[{"product_id": p2, "qty": 99999}], cashier_id=1, cashier_name="C")
        check(False, "oversell should raise")
    except InsufficientStockError:
        check(True, "oversell raises InsufficientStockError")
    check(products.get(p2)["stock_qty"] == before, "stock unchanged after rollback")
    check(sales.list_sales()["total"] == cnt_before, "no sale row created on rollback")

    print("\n[sale] duplicate product lines merged + price override")
    s5 = sales.create_sale(items=[{"product_id": p1, "qty": 1, "unit_price_minor": 31000},
                                  {"product_id": p1, "qty": 2, "unit_price_minor": 31000}],
                           cashier_id=1, cashier_name="C")
    full = sales.get_sale(s5["id"])
    check(len(full["items"]) == 1 and full["items"][0]["qty"] == 3, "duplicate lines merged to qty 3")
    check(full["items"][0]["unit_price_minor"] == 31000, "price override applied")

    print("\n[sale] void restores stock")
    stock_before = products.get(p1)["stock_qty"]
    qty_sold = full["items"][0]["qty"]
    sales.void_sale(s5["id"])
    check(products.get(p1)["stock_qty"] == stock_before + qty_sold, "void restores stock")
    check(sales.get_sale(s5["id"])["status"] == "void", "sale marked void")
    try:
        sales.void_sale(s5["id"]); check(False, "double void should raise")
    except ValidationError:
        check(True, "double void rejected")

    print("\n[sale] empty cart + history")
    try:
        sales.create_sale(items=[], cashier_id=1, cashier_name="C"); check(False, "empty raises")
    except ValidationError:
        check(True, "empty cart rejected")
    hist = sales.list_sales(status="completed")
    check(hist["total"] >= 1 and all(r["status"] == "completed" for r in hist["rows"]),
          "history filters by status")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(Path(tmp)); run(db); db.close()
    p = sum(_r)
    print(f"\n==== {p}/{len(_r)} checks passed ====")
    return 0 if p == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
