"""Headless tests for user management."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.config import Config
from lubripos.core.exceptions import AuthError, ValidationError
from lubripos.database.connection import Database
from lubripos.database.db import init_database
from lubripos.services.auth_service import AuthService
from lubripos.services.user_service import UserService

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
    users = UserService(db)
    auth = AuthService(db)
    admin = db.query_one("SELECT id FROM users WHERE username='admin'")["id"]

    print("\n[users] create + login + must_change_pw")
    uid = users.create_user(username="cashier1", password="pass123", role="cashier",
                            full_name="Cashier One", actor_id=admin)
    u = auth.authenticate("cashier1", "pass123")
    check(u.role == "cashier", "new cashier can log in")
    check(users.get(uid)["must_change_pw"] == 1, "new user flagged must_change_pw")

    print("\n[users] validation")
    try:
        users.create_user(username="cashier1", password="x12345", role="cashier")
        check(False, "duplicate username should raise")
    except ValidationError:
        check(True, "duplicate username rejected")
    try:
        users.create_user(username="shorty", password="123", role="cashier")
        check(False, "short password should raise")
    except ValidationError:
        check(True, "short password rejected")
    try:
        users.create_user(username="weird", password="pass123", role="superuser")
        check(False, "bad role should raise")
    except ValidationError:
        check(True, "invalid role rejected")

    print("\n[users] reset password")
    users.reset_password(uid, "newpass1", force_change=True, actor_id=admin)
    check(auth.authenticate("cashier1", "newpass1").id == uid, "login works with reset password")
    check(users.get(uid)["must_change_pw"] == 1, "reset forces password change")

    print("\n[users] deactivate blocks login")
    users.set_active(uid, False, actor_id=admin)
    try:
        auth.authenticate("cashier1", "newpass1"); check(False, "inactive login should fail")
    except AuthError:
        check(True, "inactive user cannot log in")
    users.set_active(uid, True, actor_id=admin)
    check(auth.authenticate("cashier1", "newpass1").id == uid, "reactivated user can log in")

    print("\n[users] role update + last-admin protection")
    users.update_user(uid, role="admin", actor_id=admin)
    check(users.get(uid)["role"] == "admin", "role promoted to admin")
    users.update_user(uid, role="cashier", actor_id=admin)  # ok, still another admin
    check(users.get(uid)["role"] == "cashier", "role demoted back (another admin exists)")
    # now 'admin' is the only active admin; demoting/deactivating it must fail
    try:
        users.update_user(admin, role="cashier", actor_id=admin)
        check(False, "demoting last admin should raise")
    except ValidationError:
        check(True, "cannot demote the last active admin")
    try:
        users.set_active(admin, False, actor_id=uid)
        check(False, "deactivating last admin should raise")
    except ValidationError:
        check(True, "cannot deactivate the last active admin")

    print("\n[users] cannot deactivate self")
    users.update_user(uid, role="admin", actor_id=admin)  # two admins again
    try:
        users.set_active(uid, False, actor_id=uid)
        check(False, "self-deactivation should raise")
    except ValidationError:
        check(True, "cannot deactivate your own account")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(Path(tmp)); run(db); db.close()
    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
