"""Headless tests for the customer directory + purchase history."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.customer_service import CustomerService
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c)); print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    cfg = Config(data_root=Path(tempfile.mkdtemp())); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    ps = ProductService(ctx.db); ss = SaleService(ctx.db, ctx.audit)
    cs = CustomerService(ctx.db, ctx.audit)

    print("\n[customers] schema")
    ver = int(ctx.db.query_one("SELECT value FROM app_meta WHERE key='schema_version'")["value"])
    check(ver >= 9, f"schema_version >= 9 (got {ver})")
    check(any(r["name"] == "customer_id" for r in ctx.db.query("PRAGMA table_info(sales)")),
          "sales.customer_id exists")

    print("\n[customers] find_or_create dedupes by name+phone")
    a = cs.find_or_create("Bilal Khan", "0300-1234567")
    b = cs.find_or_create("bilal khan", "0300 1234567")  # case + formatting differ
    check(a == b, "same name+phone (case/format-insensitive) reused")
    check(cs.get(a)["phone"] == "03001234567", "phone normalised to digits")
    c = cs.find_or_create("Bilal Khan", "0311-9999999")  # different phone
    check(c != a, "different phone -> different customer")
    try:
        cs.find_or_create("", "0300"); check(False, "empty name should raise")
    except ValidationError:
        check(True, "name is required")

    print("\n[customers] sale links a customer; walk-in stays NULL")
    pa = ps.create({"name": "Engine Oil", "sale_price_minor": 10000,
                    "purchase_price_minor": 6000, "stock_qty": 100})
    pb = ps.create({"name": "Gear Oil", "sale_price_minor": 8000,
                    "purchase_price_minor": 5000, "stock_qty": 100})
    s1 = ss.create_sale(items=[{"product_id": pa, "qty": 2}], cashier_id=1,
                        cashier_name="Cashier", customer_id=a, customer_name="Bilal Khan")
    row = ctx.db.query_one("SELECT customer_id, customer_name FROM sales WHERE id=?", (s1["id"],))
    check(row["customer_id"] == a and row["customer_name"] == "Bilal Khan", "sale carries customer")
    s_walkin = ss.create_sale(items=[{"product_id": pb, "qty": 1}], cashier_id=1,
                              cashier_name="Cashier")
    check(ctx.db.query_one("SELECT customer_id FROM sales WHERE id=?",
                           (s_walkin["id"],))["customer_id"] is None, "walk-in customer_id NULL")

    print("\n[customers] purchase history aggregates products")
    ss.create_sale(items=[{"product_id": pa, "qty": 1}, {"product_id": pb, "qty": 1}],
                   cashier_id=1, cashier_name="Cashier", customer_id=a, customer_name="Bilal Khan")
    hist = cs.history(a)
    prods = {p["product"]: p for p in hist["products"]}
    check(hist["visits"] == 2, "2 visits recorded")
    check(prods["Engine Oil"]["qty"] == 3 and prods["Engine Oil"]["visits"] == 2,
          "Engine Oil qty 3 across 2 visits")
    check("Gear Oil" in prods, "Gear Oil in history")
    check(hist["total_spent"] == 20000 + 18000, "total spent = 20000 + 18000")
    check("Engine Oil" in cs.last_products(a), "last_products lists Engine Oil")

    print("\n[customers] reorder list = live active products")
    pp = cs.purchased_products(a)
    names = {x["name"] for x in pp}
    check("Engine Oil" in names and "Gear Oil" in names, "purchased_products lists both")
    check(all("id" in x and "sale_price_minor" in x and "stock_qty" in x for x in pp),
          "reorder rows carry id/price/stock for add-to-cart")
    ctx.db.execute("UPDATE products SET is_active=0 WHERE id=?", (pb,))
    names2 = {x["name"] for x in cs.purchased_products(a)}
    check("Gear Oil" not in names2 and "Engine Oil" in names2,
          "inactive product excluded from reorder list")

    print("\n[customers] search + manage")
    check(a in [x["id"] for x in cs.search_min("Bilal")], "search by name")
    check(c in [x["id"] for x in cs.search_min("0311")], "search by phone")
    cs.update(a, {"phone": "0345-0000000"})
    check(cs.get(a)["phone"] == "03450000000", "update normalises phone")
    cs.set_active(a, False)
    check(a not in [x["id"] for x in cs.list_customers(only_active=True)["rows"]],
          "inactive hidden from active list")

    ctx.shutdown()
    n = sum(_r); print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
