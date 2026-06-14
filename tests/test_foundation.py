"""Headless smoke tests for the non-GUI foundation.

Exercises: config paths, schema creation, seeding, PBKDF2 hashing,
authentication (success/failure/inactive), forced password change, and
company/tax settings round-trip. No Qt required.

Run:  python -m pytest tests/  (or)  python tests/test_foundation.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.config import Config
from lubripos.core import security
from lubripos.core.exceptions import AuthError
from lubripos.core.money import apply_tax, format_money, from_minor, to_minor
from lubripos.database.connection import Database
from lubripos.database.db import init_database
from lubripos.services.auth_service import AuthService
from lubripos.services.company_service import CompanyService
from lubripos.services.dashboard_service import DashboardService

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results: list[tuple[bool, str]] = []


def check(cond: bool, label: str) -> None:
    _results.append((bool(cond), label))
    print(f"  {PASS if cond else FAIL}  {label}")


def make_db(tmp: Path) -> Database:
    cfg = Config(data_root=tmp)
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    init_database(db)
    return db


def test_security() -> None:
    print("\n[security] PBKDF2 hashing")
    h, salt, iters = security.hash_password("S3cret!")
    check(security.verify_password("S3cret!", h, salt, iters), "correct password verifies")
    check(not security.verify_password("wrong", h, salt, iters), "wrong password rejected")
    h2, salt2, _ = security.hash_password("S3cret!")
    check(salt != salt2 and h != h2, "salt is unique per hash")


def test_money() -> None:
    print("\n[money] integer minor-unit math")
    check(to_minor("1500.50") == 150050, "to_minor parses decimals")
    check(str(from_minor(150050)) == "1500.50", "from_minor round-trips")
    check(format_money(450000, "Rs") == "Rs 4,500.00", "format_money formats with grouping")
    base, tax = apply_tax(100000, 1700)  # 17% exclusive on 1000.00
    check(tax == 17000, "exclusive tax 17% of 1000.00 == 170.00")
    base_i, tax_i = apply_tax(117000, 1700, inclusive=True)
    check(base_i == 100000 and tax_i == 17000, "inclusive tax backs out correctly")


def test_schema_and_seed(db: Database) -> None:
    print("\n[schema] tables + seed data")
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    required = {
        "users", "products", "categories", "brands", "suppliers", "purchases",
        "purchase_items", "sales", "sale_items", "expenses", "company_settings",
        "tax_settings", "backups", "audit_logs",
    }
    check(required.issubset(tables), "all 14 core tables exist")
    check(db.query_one("SELECT COUNT(*) n FROM categories")["n"] == 8, "8 default categories seeded")
    check(db.query_one("SELECT COUNT(*) n FROM brands")["n"] == 6, "6 default brands seeded")
    check(db.query_one("SELECT COUNT(*) n FROM company_settings WHERE id=1")["n"] == 1,
          "company_settings singleton seeded")
    check(db.query_one("SELECT COUNT(*) n FROM users WHERE role='admin'")["n"] == 1,
          "default admin seeded")
    # idempotency
    from lubripos.database.seed import seed_all
    seed_all(db)
    check(db.query_one("SELECT COUNT(*) n FROM categories")["n"] == 8,
          "re-seeding does not duplicate")


def test_fk_enforced(db: Database) -> None:
    print("\n[schema] foreign keys enforced")
    try:
        db.execute("INSERT INTO purchase_items (purchase_id, product_id, qty, "
                   "unit_cost_minor, line_total_minor) VALUES (9999, 9999, 1, 1, 1)")
        check(False, "FK violation should raise")
    except Exception:
        check(True, "FK violation correctly rejected")


def test_auth(db: Database) -> None:
    print("\n[auth] authentication")
    auth = AuthService(db)
    user = auth.authenticate("admin", "admin123")
    check(user.role == "admin", "valid admin login succeeds")
    check(auth.must_change_password(user.id), "seeded admin flagged must_change_pw")
    try:
        auth.authenticate("admin", "bad"); check(False, "bad password should raise")
    except AuthError:
        check(True, "bad password raises AuthError")
    try:
        auth.authenticate("ghost", "x"); check(False, "unknown user should raise")
    except AuthError:
        check(True, "unknown user raises AuthError")
    auth.change_password(user.id, "newpass1")
    check(not auth.must_change_password(user.id), "must_change_pw cleared after change")
    check(auth.authenticate("admin", "newpass1").id == user.id, "login with new password works")


def test_company(db: Database) -> None:
    print("\n[company] white-label settings round-trip")
    svc = CompanyService(db)
    svc.update_company({"shop_name": "Afridi Lubricants", "currency_symbol": "Rs"})
    check(svc.get_company()["shop_name"] == "Afridi Lubricants", "shop name persists")
    svc.update_tax({"tax_rate_bps": 1700, "tax_enabled": 1})
    check(svc.get_tax()["tax_rate_bps"] == 1700, "tax rate persists")
    # rejects unknown/injection-y keys (whitelist)
    svc.update_company({"id": 999, "evil": "x", "shop_name": "Khan Oil Store"})
    check(svc.get_company()["id"] == 1 and svc.get_company()["shop_name"] == "Khan Oil Store",
          "field whitelist blocks non-allowed columns")


def test_dashboard(db: Database) -> None:
    print("\n[dashboard] aggregates on empty data")
    s = DashboardService(db).summary()
    check(s["today_sales_minor"] == 0 and s["low_stock_count"] == 0,
          "summary returns zeros with no data")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(Path(tmp))
        test_security()
        test_money()
        test_schema_and_seed(db)
        test_fk_enforced(db)
        test_auth(db)
        test_company(db)
        test_dashboard(db)
        db.close()

    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print(f"\n==== {passed}/{total} checks passed ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
