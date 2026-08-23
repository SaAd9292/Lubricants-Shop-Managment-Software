"""Headless tests: optional customer address; name required, phone optional."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.exceptions import ValidationError
from lubripos.services.customer_service import CustomerService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    cs = CustomerService(ctx.db, ctx.audit)

    print("\n[address] schema + optionality")
    cols = {r["name"] for r in ctx.db.query("PRAGMA table_info(customers)")}
    check("address" in cols, "customers.address column exists")

    cid = cs.create({"name": "Walk In"})
    c = cs.get(cid)
    check(c["phone"] == "" and not c["address"], "name-only: phone + address optional (blank)")

    cid2 = cs.create({"name": "Ahmed Khan", "address": "Saddar Road, Peshawar"})
    check(cs.get(cid2)["address"] == "Saddar Road, Peshawar", "address saved on create")
    check(cs.get(cid2)["phone"] == "", "phone still optional when address given")

    cs.update(cid2, {"address": "University Road"})
    check(cs.get(cid2)["address"] == "University Road", "address editable")

    print("\n[address] name still required")
    try:
        cs.create({"name": "   ", "address": "x", "phone": "0300"})
        check(False, "empty name should raise")
    except ValidationError:
        check(True, "empty name rejected (name is the only required field)")

    total, passed = len(_r), sum(_r)
    print(f"\n[address] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
