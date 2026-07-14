"""Lightweight, idempotent schema migrations for existing databases.

`schema.sql` uses CREATE TABLE IF NOT EXISTS, so it never alters tables that
already exist. Anything that must change on an installed database goes here.
Each migration checks current state before acting, so running on every startup
is safe. app_meta.schema_version records the latest applied version.
"""
from __future__ import annotations

from ..core.logging_config import get_logger
from .connection import Database

log = get_logger(__name__)

CURRENT_VERSION = 7


def run_migrations(db: Database) -> None:
    _migration_2_drop_product_image(db)
    _migration_3_relax_backup_type(db)
    _migration_4_add_product_markup(db)
    _migration_5_payment_accounts(db)
    _migration_6_user_permissions(db)
    _migration_7_partial_returns(db)
    db.execute(
        "INSERT INTO app_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(CURRENT_VERSION),),
    )


def _column_exists(db: Database, table: str, column: str) -> bool:
    rows = db.query(f"PRAGMA table_info({table})")
    return any(r["name"] == column for r in rows)


def _migration_2_drop_product_image(db: Database) -> None:
    """v2: products.image_path removed (product images feature dropped)."""
    if not _column_exists(db, "products", "image_path"):
        return
    try:
        db.execute("ALTER TABLE products DROP COLUMN image_path")
        log.info("Migration: dropped products.image_path")
    except Exception:
        # DROP COLUMN needs SQLite >= 3.35. If unavailable, leave the column
        # in place (harmless, nullable) rather than fail startup.
        log.warning("Could not drop products.image_path (SQLite too old?); "
                    "leaving it in place - it is unused and harmless.")


def _migration_3_relax_backup_type(db: Database) -> None:
    """v3: allow backup_type 'pre_restore' (added for safety backups).

    The original CHECK only permitted 'auto'/'manual'. Rebuild the (small,
    non-referenced) backups table with the expanded constraint. Idempotent:
    skips if the new value is already allowed.
    """
    row = db.query_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='backups'")
    if not row or "pre_restore" in (row["sql"] or ""):
        return
    conn = db.connect()
    conn.executescript(
        """
        CREATE TABLE backups_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path       TEXT    NOT NULL,
            file_size_bytes INTEGER,
            backup_type     TEXT    NOT NULL DEFAULT 'manual'
                                CHECK (backup_type IN ('auto','manual','pre_restore')),
            created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        INSERT INTO backups_new (id, file_path, file_size_bytes, backup_type, created_by, created_at)
            SELECT id, file_path, file_size_bytes, backup_type, created_by, created_at FROM backups;
        DROP TABLE backups;
        ALTER TABLE backups_new RENAME TO backups;
        """
    )
    log.info("Migration: relaxed backups.backup_type to allow 'pre_restore'")


def _migration_4_add_product_markup(db: Database) -> None:
    """v4: products.markup_bps (markup-over-cost pricing).

    Adds the column, then BACK-FILLS each existing product's implied markup from
    its current sale/cost so prices don't change on the first purchase after the
    upgrade. Products with no cost, or priced at/below cost, keep markup 0 (which
    means 'manual price -- never auto-derived').
    """
    if _column_exists(db, "products", "markup_bps"):
        return
    db.execute(
        "ALTER TABLE products ADD COLUMN markup_bps INTEGER NOT NULL DEFAULT 0")
    db.execute(
        "UPDATE products SET markup_bps = CAST(ROUND("
        "  (sale_price_minor - purchase_price_minor) * 10000.0 / purchase_price_minor"
        ") AS INTEGER) "
        "WHERE purchase_price_minor > 0 AND sale_price_minor > purchase_price_minor")
    log.info("Migration: added products.markup_bps and back-filled implied markup")



def _migration_5_payment_accounts(db: Database) -> None:
    """v5: named payment accounts (multiple Bank/EasyPaisa/JazzCash) + link the
    sale to the account that received the money (name snapshot survives delete)."""
    db.connect().executescript(
        """
        CREATE TABLE IF NOT EXISTS payment_accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            method       TEXT    NOT NULL CHECK (method IN ('Bank','EasyPaisa','JazzCash')),
            name         TEXT    NOT NULL,
            account_no   TEXT,
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_payacct_method ON payment_accounts(method);
        """
    )
    if not _column_exists(db, "sales", "payment_account_id"):
        db.execute("ALTER TABLE sales ADD COLUMN payment_account_id INTEGER "
                   "REFERENCES payment_accounts(id) ON DELETE SET NULL")
    if not _column_exists(db, "sales", "payment_account_name"):
        db.execute("ALTER TABLE sales ADD COLUMN payment_account_name TEXT")
    log.info("Migration: added payment_accounts table + sales account link")



def _migration_6_user_permissions(db: Database) -> None:
    """v6: per-user privileges (users.permissions = JSON grant list). Existing
    non-admin accounts are backfilled with the legacy cashier screens so they
    keep working; admins ignore the column entirely."""
    from ..core import permissions as perms
    if not _column_exists(db, "users", "permissions"):
        db.execute("ALTER TABLE users ADD COLUMN permissions TEXT")
    db.execute(
        "UPDATE users SET permissions = ? "
        "WHERE role != 'admin' AND (permissions IS NULL OR permissions = '')",
        (perms.serialize(perms.DEFAULT_CASHIER),))
    log.info("Migration: added users.permissions + backfilled non-admin defaults")



def _migration_7_partial_returns(db: Database) -> None:
    """v7: partial / line-level returns. Adds sale_items.returned_qty plus the
    sale_returns + sale_return_items ledger tables."""
    if not _column_exists(db, "sale_items", "returned_qty"):
        db.execute("ALTER TABLE sale_items ADD COLUMN returned_qty INTEGER NOT NULL DEFAULT 0")
    db.connect().executescript(
        """
        CREATE TABLE IF NOT EXISTS sale_returns (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id      INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
            return_date  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
            refund_minor INTEGER NOT NULL DEFAULT 0 CHECK (refund_minor >= 0),
            notes        TEXT,
            created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_returns_sale ON sale_returns(sale_id);
        CREATE INDEX IF NOT EXISTS idx_returns_date ON sale_returns(return_date);
        CREATE TABLE IF NOT EXISTS sale_return_items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id        INTEGER NOT NULL REFERENCES sale_returns(id) ON DELETE CASCADE,
            sale_item_id     INTEGER REFERENCES sale_items(id),
            product_id       INTEGER REFERENCES products(id),
            product_name     TEXT    NOT NULL,
            qty              INTEGER NOT NULL CHECK (qty > 0),
            unit_price_minor INTEGER NOT NULL,
            unit_cost_minor  INTEGER NOT NULL DEFAULT 0,
            line_total_minor INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ritems_return ON sale_return_items(return_id);
        """
    )
    log.info("Migration: added partial-return ledger (sale_returns + items)")
