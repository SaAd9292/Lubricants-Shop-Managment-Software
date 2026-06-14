"""Headless tests for the expenses service (no Qt)."""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.config import Config
from lubripos.core.exceptions import NotFoundError, ValidationError
from lubripos.database.connection import Database
from lubripos.database.db import init_database
from lubripos.services.dashboard_service import DashboardService
from lubripos.services.expense_service import ExpenseService

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
    svc = ExpenseService(db)

    print("\n[expenses] default categories + add")
    cats = {c["name"] for c in svc.list_categories()}
    check({"Rent", "Electricity", "Salaries", "Miscellaneous"}.issubset(cats),
          "4 default expense categories seeded")
    cid = svc.add_category("Fuel")
    check(svc.add_category("Fuel") == cid, "re-adding category is idempotent")

    print("\n[expenses] create / validation")
    today = date.today().isoformat()
    e1 = svc.create({"expense_date": today + " 00:00:00", "category": "Rent",
                     "amount_minor": 5000000, "description": "Shop rent June"}, user_id=1)
    check(svc.get(e1)["amount_minor"] == 5000000, "expense created with amount")
    try:
        svc.create({"category": "", "amount_minor": 100}); check(False, "empty category raises")
    except ValidationError:
        check(True, "empty category rejected")
    try:
        svc.create({"category": "Rent", "amount_minor": -1}); check(False, "negative raises")
    except ValidationError:
        check(True, "negative amount rejected")

    print("\n[expenses] update / delete")
    svc.update(e1, {"amount_minor": 5500000})
    check(svc.get(e1)["amount_minor"] == 5500000, "update persists")
    svc.create({"expense_date": today + " 00:00:00", "category": "Electricity",
                "amount_minor": 1200000, "description": "WAPDA"}, user_id=1)
    svc.delete(e1)
    try:
        svc.get(e1); check(False, "deleted expense should be gone")
    except NotFoundError:
        check(True, "delete removes the row")

    print("\n[expenses] filters + sum")
    svc.create({"category": "Rent", "amount_minor": 300000, "description": "misc rent"}, user_id=1)
    by_cat = svc.list_expenses(category="Electricity")
    check(by_cat["total"] == 1 and by_cat["sum_minor"] == 1200000, "category filter + sum")
    by_search = svc.list_expenses(search="WAPDA")
    check(by_search["total"] == 1, "description search")

    print("\n[expenses] dashboard reflects today's expenses")
    summ = DashboardService(db).summary()
    check(summ["today_expenses_minor"] == 1200000 + 300000,
          "dashboard today-expenses sums today's rows")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(Path(tmp)); run(db); db.close()
    p = sum(_r)
    print(f"\n==== {p}/{len(_r)} checks passed ====")
    return 0 if p == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
