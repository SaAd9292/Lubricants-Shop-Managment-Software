"""Headless tests for per-user privileges (screens + actions)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core import permissions as perms
from lubripos.core.session import CurrentUser, current_session
from lubripos.controllers.sale_controller import SaleController
from lubripos.database.migrations import _migration_6_user_permissions
from lubripos.services.auth_service import AuthService
from lubripos.services.product_service import ProductService
from lubripos.services.sale_service import SaleService
from lubripos.services.user_service import UserService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(config=(lambda c: (c.ensure_dirs(), c)[1])(Config(data_root=Path(tempfile.mkdtemp()))))
    us = UserService(ctx.db)
    auth = AuthService(ctx.db)

    print("\n[perms] module helpers")
    check(perms.clean(["reports", "junk", "pos", "reports"]) == ["pos", "reports"],
          "clean() filters junk, dedupes, canonical order")
    check(perms.parse(perms.serialize(["sale.void", "x"])) == {"sale.void"},
          "serialize/parse round-trip drops invalid keys")
    check(perms.parse(None) == set() and perms.parse("not-json") == set(),
          "parse() robust to null/garbage")

    print("\n[perms] create + read")
    uid = us.create_user(username="c1", password="pass123", role="cashier",
                         permissions=["dashboard", "pos", "sales", "sale.void"])
    check(set(us.get(uid)["permissions"]) == {"dashboard", "pos", "sales", "sale.void"},
          "create_user stores + get returns permissions")

    print("\n[perms] migration backfill")
    ctx.db.execute(
        "INSERT INTO users (username, full_name, password_hash, password_salt, "
        "pwd_iterations, role, permissions) VALUES ('legacy','L','x','y',1,'cashier',NULL)")
    _migration_6_user_permissions(ctx.db)
    lid = ctx.db.query_one("SELECT id FROM users WHERE username='legacy'")["id"]
    check(set(us.get(lid)["permissions"]) == set(perms.DEFAULT_CASHIER),
          "legacy cashier backfilled with default screens")

    print("\n[perms] session.can via login")
    cu = auth.authenticate("c1", "pass123")
    current_session.login(cu)
    check(current_session.can("sale.void") and not current_session.can("products"),
          "session.can reflects the grant list")
    current_session.login(CurrentUser(id=1, username="admin", full_name="A", role="admin"))
    check(current_session.can("settings") and current_session.can("sale.discount"),
          "admin implicitly can do everything")

    print("\n[perms] action enforcement (void + discount)")
    pid = ProductService(ctx.db).create({"name": "Oil", "sale_price_minor": 10000,
                                         "purchase_price_minor": 5000, "stock_qty": 9})
    sc = SaleController(ctx)
    # c1 has sale.void
    current_session.login(cu)
    s1 = SaleService(ctx.db).create_sale(items=[{"product_id": pid, "qty": 1}],
                                         cashier_id=cu.id, cashier_name="c1", payment_method="Cash")
    ok, _, _ = sc.void(s1["id"])
    check(ok, "cashier WITH sale.void can reverse a sale")
    # c2 lacks sale.void + discount
    uid2 = us.create_user(username="c2", password="pass123", role="cashier",
                          permissions=["dashboard", "pos", "sales"])
    cu2 = auth.authenticate("c2", "pass123")
    current_session.login(cu2)
    s2 = SaleService(ctx.db).create_sale(items=[{"product_id": pid, "qty": 1}],
                                         cashier_id=cu2.id, cashier_name="c2", payment_method="Cash")
    ok, msg, _ = sc.void(s2["id"])
    check(not ok, "cashier WITHOUT sale.void is blocked from reversing")
    ok, msg, _ = sc.checkout(lines=[{"product_id": pid, "qty": 1, "unit_price": 100.0}],
                             discount=50.0, payment_method="Cash")
    check(not ok and "discount" in msg.lower(),
          "cashier WITHOUT sale.discount is blocked from discounting")

    ctx.shutdown()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
