"""Headless tests: manual stock adjustment + audit trail."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.product_service import ProductService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    products = ProductService(ctx.db, ctx.audit)

    print("\n[stock-adjust] set + audit")
    pid = products.create({"name": "Test Oil", "stock_qty": 10})
    new = products.adjust_stock(pid, 7, "Stock count correction", user_id=1)
    check(new == 7, "returns new qty")
    check(products.get(pid)["stock_qty"] == 7, "stock updated to counted value")

    logs = ctx.audit.list_logs(action="ADJUST_STOCK")
    check(logs["total"] == 1, "one ADJUST_STOCK audit entry")
    import json
    details = json.loads(logs["rows"][0]["details"])
    check(details["from"] == 10 and details["to"] == 7 and details["delta"] == -3,
          "audit records from/to/delta")
    check("count" in details["reason"].lower(), "audit records reason")

    print("\n[stock-adjust] guards")
    try:
        products.adjust_stock(pid, -1, "bad", user_id=1)
        check(False, "negative qty should raise")
    except ValidationError:
        check(True, "negative qty rejected")

    print("\n[audit] list + search")
    all_logs = ctx.audit.list_logs()
    check(all_logs["total"] >= 1, "audit list returns entries")
    check("ADJUST_STOCK" in ctx.audit.distinct_actions(), "distinct_actions includes ADJUST_STOCK")

    total, passed = len(_r), sum(_r)
    print(f"\n[stock-adjust] {passed}/{total} checks passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
