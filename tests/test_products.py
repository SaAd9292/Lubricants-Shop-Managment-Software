"""Headless tests for the products + taxonomy services (no Qt)."""
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
from lubripos.services.taxonomy_service import TaxonomyService

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
    tax = TaxonomyService(db)
    svc = ProductService(db)

    print("\n[taxonomy] add + idempotency")
    zic = next(b["id"] for b in tax.list_brands() if b["name"] == "ZIC")
    engine = next(c["id"] for c in tax.list_categories() if c["name"] == "Engine Oil")
    again = tax.add_brand("ZIC")
    check(again == zic, "re-adding existing brand returns same id (no duplicate)")
    new_brand = tax.add_brand("Castrol")
    check(any(b["name"] == "Castrol" for b in tax.list_brands()), "new brand added")

    print("\n[products] create + minor-unit storage")
    pid = svc.create({
        "name": "ZIC X7 5W-30 4L", "barcode": "8801234567890",
        "brand_id": zic, "category_id": engine, "unit_type": "Bottle",
        "purchase_price_minor": 250000, "sale_price_minor": 300000,
        "stock_qty": 10, "min_stock_level": 3,
    })
    p = svc.get(pid)
    check(p["sale_price_minor"] == 300000, "sale price stored as minor units")
    check(p["brand_name"] == "ZIC" and p["category_name"] == "Engine Oil",
          "join returns brand/category names")

    print("\n[products] barcode uniqueness")
    try:
        svc.create({"name": "Dup", "barcode": "8801234567890",
                    "sale_price_minor": 1, "purchase_price_minor": 1})
        check(False, "duplicate barcode should raise")
    except ValidationError as e:
        check("already used" in str(e), "duplicate barcode rejected with friendly message")

    print("\n[products] validation")
    try:
        svc.create({"name": "  ", "sale_price_minor": 1})
        check(False, "empty name should raise")
    except ValidationError:
        check(True, "empty name rejected")
    try:
        svc.create({"name": "Neg", "sale_price_minor": -5})
        check(False, "negative price should raise")
    except ValidationError:
        check(True, "negative price rejected")

    print("\n[products] update + soft delete")
    svc.update(pid, {"sale_price_minor": 320000, "stock_qty": 2})
    check(svc.get(pid)["sale_price_minor"] == 320000, "update persists")
    svc.set_active(pid, False)
    check(svc.list_products()["total"] == 0, "soft-deleted product hidden from active list")
    check(svc.list_products(only_active=False)["total"] >= 1, "still visible when including inactive")
    svc.set_active(pid, True)

    print("\n[products] search / filter / low-stock / pagination")
    # seed extra products for pagination & search
    for i in range(30):
        svc.create({"name": f"Filter Oil {i:02d}", "category_id": engine,
                    "sale_price_minor": 1000 + i, "purchase_price_minor": 900,
                    "stock_qty": 50, "min_stock_level": 5})
    res = svc.list_products(search="ZIC X7")
    check(res["total"] == 1, "search matches by name")
    res = svc.list_products(search="8801234567890")
    check(res["total"] == 1, "search matches by barcode")
    low = svc.list_products(low_stock_only=True)
    check(all(r["stock_qty"] <= r["min_stock_level"] for r in low["rows"]),
          "low-stock filter returns only low rows")
    page0 = svc.list_products(limit=10, offset=0, sort_by="name", sort_dir="asc")
    page1 = svc.list_products(limit=10, offset=10, sort_by="name", sort_dir="asc")
    check(len(page0["rows"]) == 10 and page0["total"] > 10, "pagination limit works")
    check(page0["rows"][0]["id"] != page1["rows"][0]["id"], "pages differ")
    asc = svc.list_products(sort_by="sale_price", sort_dir="asc")["rows"]
    desc = svc.list_products(sort_by="sale_price", sort_dir="desc")["rows"]
    check(asc[0]["sale_price_minor"] <= asc[-1]["sale_price_minor"], "asc sort ordered")
    check(desc[0]["sale_price_minor"] >= desc[-1]["sale_price_minor"], "desc sort ordered")

    print("\n[products] not found")
    try:
        svc.get(999999)
        check(False, "missing product should raise")
    except NotFoundError:
        check(True, "missing product raises NotFoundError")

    print("\n[security] sort key whitelist (injection-proof)")
    # a bogus sort key must fall back to a safe default, not break/inject
    res = svc.list_products(sort_by="name; DROP TABLE products--")
    check(res["total"] > 0, "malicious sort key safely ignored")


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
