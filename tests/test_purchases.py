"""Headless tests for suppliers + purchases (no Qt).

Focus: supplier CRUD, atomic stock-in, total correctness, last-cost update,
transaction rollback on a bad line, and history retrieval.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.config import Config
from lubripos.core.exceptions import NotFoundError, ValidationError
from lubripos.database.connection import Database
from lubripos.database.db import init_database
from lubripos.services.product_service import ProductService
from lubripos.services.purchase_service import PurchaseService
from lubripos.services.supplier_service import SupplierService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_results: list[bool] = []


def check(cond: bool, label: str) -> None:
    _results.append(bool(cond))
    print(f"  {PASS if cond else FAIL}  {label}")


def make_db(tmp: Path) -> Database:
    cfg = Config(data_root=tmp)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    init_database(db)
    return db


def run(db: Database) -> None:
    suppliers = SupplierService(db)
    products = ProductService(db)
    purchases = PurchaseService(db)

    print("\n[suppliers] CRUD + search + soft delete")
    sid = suppliers.create({"name": "Khan Traders", "phone": "0300-1234567",
                            "address": "Karkhano Market", "notes": "GST registered"})
    check(suppliers.get(sid)["name"] == "Khan Traders", "create + get")
    suppliers.create({"name": "Peshawar Oil Co", "phone": "091-555000"})
    suppliers.update(sid, {"phone": "0301-0000000"})
    check(suppliers.get(sid)["phone"] == "0301-0000000", "update persists")
    check(suppliers.list_suppliers(search="Khan")["total"] == 1, "search by name")
    suppliers.set_active(sid, False)
    check(suppliers.list_suppliers()["total"] == 1, "soft-deleted supplier hidden")
    check(suppliers.list_suppliers(only_active=False)["total"] == 2, "shown when inactive included")
    suppliers.set_active(sid, True)
    try:
        suppliers.create({"name": "   "}); check(False, "empty name should raise")
    except ValidationError:
        check(True, "empty supplier name rejected")

    print("\n[purchases] atomic stock-in + total + last-cost")
    p1 = products.create({"name": "ZIC X7 4L", "sale_price_minor": 300000,
                          "purchase_price_minor": 250000, "stock_qty": 10, "min_stock_level": 3})
    p2 = products.create({"name": "Shell HX7 4L", "sale_price_minor": 270000,
                          "purchase_price_minor": 220000, "stock_qty": 5, "min_stock_level": 2})
    pur_id = purchases.create_purchase(
        supplier_id=sid,
        items=[
            {"product_id": p1, "qty": 12, "unit_cost_minor": 260000},
            {"product_id": p2, "qty": 8, "unit_cost_minor": 225000},
        ],
        supplier_invoice_no="BILL-001",
    )
    check(products.get(p1)["stock_qty"] == 22, "product 1 stock increased 10 -> 22")
    check(products.get(p2)["stock_qty"] == 13, "product 2 stock increased 5 -> 13")
    check(products.get(p1)["purchase_price_minor"] == 260000, "last-cost updates product price")
    head = purchases.get_purchase(pur_id)
    expected_total = 12 * 260000 + 8 * 225000
    check(head["total_minor"] == expected_total, "purchase total = sum of line totals")
    check(len(head["items"]) == 2, "two line items recorded")

    print("\n[purchases] transaction rollback on bad line")
    stock_before = products.get(p1)["stock_qty"]
    count_before = purchases.list_purchases()["total"]
    try:
        purchases.create_purchase(
            supplier_id=sid,
            items=[
                {"product_id": p1, "qty": 5, "unit_cost_minor": 260000},
                {"product_id": 999999, "qty": 1, "unit_cost_minor": 100},  # bad
            ],
        )
        check(False, "purchase with missing product should raise")
    except NotFoundError:
        check(True, "missing product raises NotFoundError")
    check(products.get(p1)["stock_qty"] == stock_before, "stock unchanged after rollback")
    check(purchases.list_purchases()["total"] == count_before, "no purchase row created on rollback")

    print("\n[purchases] validation + history")
    try:
        purchases.create_purchase(supplier_id=sid, items=[])
        check(False, "empty purchase should raise")
    except ValidationError:
        check(True, "empty purchase rejected")
    try:
        purchases.create_purchase(supplier_id=sid,
                                  items=[{"product_id": p1, "qty": 0, "unit_cost_minor": 1}])
        check(False, "zero qty should raise")
    except ValidationError:
        check(True, "zero quantity rejected")
    hist = purchases.list_purchases(supplier_id=sid)
    check(hist["total"] == 1 and hist["rows"][0]["supplier_name"] == "Khan Traders",
          "history lists purchase with supplier name")
    check(hist["rows"][0]["line_count"] == 2 and hist["rows"][0]["total_qty"] == 20,
          "history shows line count and total qty")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(Path(tmp))
        run(db)
        db.close()
    passed = sum(_results)
    print(f"\n==== {passed}/{len(_results)} checks passed ====")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
