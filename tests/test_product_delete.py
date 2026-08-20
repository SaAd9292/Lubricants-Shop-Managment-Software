"""Headless tests: permanent product delete (guarded by inactive + no history)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import NotFoundError, ValidationError
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    ps = ProductService(ctx.db, ctx.audit)
    sales = SaleService(ctx.db)

    print("\n[delete] active product cannot be hard-deleted")
    pid = ps.create({"name": "Mistake Product", "sale_price_minor": 100, "stock_qty": 0})
    try:
        ps.hard_delete(pid, user_id=1)
        check(False, "active delete should raise")
    except ValidationError:
        check(True, "must deactivate before deleting")

    print("\n[delete] inactive product with NO history is removed")
    ps.set_active(pid, False, user_id=1)
    ps.hard_delete(pid, user_id=1)
    try:
        ps.get(pid)
        check(False, "product should be gone")
    except NotFoundError:
        check(True, "product permanently deleted")

    print("\n[delete] product WITH sales history is protected")
    pid2 = ps.create({"name": "Sold Product", "sale_price_minor": 500, "stock_qty": 10})
    sales.create_sale(items=[{"product_id": pid2, "qty": 1}],
                      cashier_id=1, cashier_name="admin", payment_method="Cash")
    ps.set_active(pid2, False, user_id=1)
    try:
        ps.hard_delete(pid2, user_id=1)
        check(False, "delete with history should raise")
    except ValidationError:
        check(True, "product with sales history is protected")
    check(ps.get(pid2) is not None, "protected product still exists (deactivated)")

    total, passed = len(_r), sum(_r)
    print(f"\n[delete] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
