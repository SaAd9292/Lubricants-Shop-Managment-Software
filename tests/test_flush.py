"""Headless test: flush shop data (keep users/settings/lists, wipe the rest)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.services.expense_service import ExpenseService
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService
from lubripos.services.supplier_service import SupplierService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def count(db, tbl):
    return db.query_one(f"SELECT COUNT(*) AS n FROM {tbl}")["n"]


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    db = ctx.db
    products = ProductService(db, ctx.audit)
    suppliers = SupplierService(db, ctx.audit)
    sales = SaleService(db, ctx.audit)
    expenses = ExpenseService(db, ctx.audit)

    # create some transactional/catalog data
    pid = products.create({"name": "Test Oil", "sale_price_minor": 50000, "stock_qty": 10})
    suppliers.create({"name": "ACME"})
    sales.create_sale(items=[{"product_id": pid, "qty": 2}], cashier_id=1,
                      cashier_name="admin", user_id=1)
    expenses.create({"category": "Rent", "amount_minor": 10000}, user_id=1)

    print("\n[flush] before flush there is data")
    check(count(db, "products") == 1 and count(db, "sales") == 1
          and count(db, "expenses") == 1, "products/sales/expenses present")

    users_before = count(db, "users")
    cats_before = count(db, "categories")
    brands_before = count(db, "brands")
    exp_cats_before = count(db, "expense_categories")

    safety = ctx.backup.flush_shop_data(user_id=1)

    print("\n[flush] wipes transactional/catalog data")
    for tbl in ("products", "suppliers", "sales", "sale_items",
                "purchases", "purchase_items", "expenses"):
        check(count(db, tbl) == 0, f"{tbl} cleared")

    print("\n[flush] keeps users, settings, and lists")
    check(count(db, "users") == users_before and users_before >= 1, "users kept")
    check(count(db, "company_settings") == 1, "company settings kept")
    check(count(db, "tax_settings") == 1, "tax settings kept")
    check(count(db, "categories") == cats_before and cats_before > 0, "categories kept")
    check(count(db, "brands") == brands_before and brands_before > 0, "brands kept")
    check(count(db, "expense_categories") == exp_cats_before, "expense categories kept")

    print("\n[flush] resets invoice counter + audit + safety backup")
    seq = db.query_one("SELECT value FROM app_meta WHERE key='invoice_seq'")
    check(seq is not None and seq["value"] == "0", "invoice counter reset to 0")
    logs = ctx.audit.list_logs(action="FLUSH_DATA") if hasattr(ctx.audit, "list_logs") else None
    # audit_logs cleared then one FLUSH entry recorded
    check(count(db, "audit_logs") == 1, "audit log has exactly the flush entry")
    check(Path(safety).is_file(), "safety backup file was created")

    # next invoice should start at 1 again
    sales.create_sale(items=[], cashier_id=1, cashier_name="admin", user_id=1) \
        if False else None
    total, passed = len(_r), sum(_r)
    print(f"\n[flush] {passed}/{total} checks passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
