"""First-run seed data: default taxonomy, tax/company config, admin user.

Idempotent: safe to run on every startup. Uses INSERT OR IGNORE / existence
checks so re-running never duplicates rows or resets user edits.

The seeded admin (admin / admin123) is flagged must_change_pw = 1 so the UI
forces a password change on first login. NO shop name is hardcoded — the
company row is created with a neutral placeholder the owner edits in Settings.
"""
from __future__ import annotations

from ..core import security
from ..core.logging_config import get_logger
from .connection import Database

log = get_logger(__name__)

DEFAULT_CATEGORIES = [
    "Engine Oil", "Bike Oil", "Gear Oil", "Hydraulic Oil",
    "Grease", "Coolant", "Brake Fluid", "Transmission Oil",
]
DEFAULT_BRANDS = ["ZIC", "Shell", "Total", "Kixx", "Caltex", "Havoline"]
DEFAULT_EXPENSE_CATEGORIES = ["Rent", "Electricity", "Salaries", "Miscellaneous"]

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"


def seed_all(db: Database) -> None:
    _seed_singletons(db)
    _seed_lookup(db, "categories", DEFAULT_CATEGORIES)
    _seed_lookup(db, "brands", DEFAULT_BRANDS)
    _seed_expense_categories(db)
    _seed_admin(db)
    log.info("Seed complete")


def _seed_singletons(db: Database) -> None:
    db.execute(
        "INSERT OR IGNORE INTO company_settings (id, shop_name) VALUES (1, 'My Shop')"
    )
    db.execute(
        "INSERT OR IGNORE INTO tax_settings (id, tax_enabled, tax_label, tax_rate_bps) "
        "VALUES (1, 1, 'GST', 0)"
    )
    db.execute(
        "INSERT OR IGNORE INTO app_meta (key, value) VALUES ('schema_version', '1')"
    )


def _seed_lookup(db: Database, table: str, names: list[str]) -> None:
    for name in names:
        db.execute(f"INSERT OR IGNORE INTO {table} (name) VALUES (?)", (name,))


def _seed_expense_categories(db: Database) -> None:
    for name in DEFAULT_EXPENSE_CATEGORIES:
        db.execute(
            "INSERT OR IGNORE INTO expense_categories (name) VALUES (?)", (name,)
        )


def _seed_admin(db: Database) -> None:
    existing = db.query_one("SELECT COUNT(*) AS n FROM users")
    if existing and existing["n"] > 0:
        return
    pwd_hash, salt, iters = security.hash_password(DEFAULT_ADMIN_PASSWORD)
    db.execute(
        "INSERT INTO users (username, full_name, password_hash, password_salt, "
        "pwd_iterations, role, must_change_pw) VALUES (?,?,?,?,?,?,1)",
        (DEFAULT_ADMIN_USERNAME, "Administrator", pwd_hash, salt, iters, "admin"),
    )
    log.warning(
        "Seeded default admin '%s' with a temporary password "
        "(must be changed on first login).",
        DEFAULT_ADMIN_USERNAME,
    )
