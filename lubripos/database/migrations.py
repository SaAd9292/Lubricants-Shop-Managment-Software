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

CURRENT_VERSION = 19


def run_migrations(db: Database) -> None:
    _migration_2_drop_product_image(db)
    _migration_3_relax_backup_type(db)
    _migration_4_add_product_markup(db)
    _migration_5_payment_accounts(db)
    _migration_6_user_permissions(db)
    _migration_7_partial_returns(db)
    _migration_8_supplier_payables(db)
    _migration_9_customers(db)
    _migration_10_ui_prefs(db)
    _migration_11_product_sort_order(db)
    _migration_12_price_history(db)
    _migration_13_customer_debt(db)
    _migration_14_custpay_account(db)
    _migration_15_opening_debt(db)
    _migration_18_product_packing(db)
    _migration_19_drop_cash_drawer(db)
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


def _migration_8_supplier_payables(db: Database) -> None:
    """v8: supplier payables. Adds purchases.amount_paid_minor (BACK-FILLED to
    the full total, so existing purchases are treated as already paid and no
    phantom debt appears on upgrade) plus the supplier_payments ledger."""
    if not _column_exists(db, "purchases", "amount_paid_minor"):
        db.execute("ALTER TABLE purchases ADD COLUMN amount_paid_minor "
                   "INTEGER NOT NULL DEFAULT 0")
        # legacy purchases: assume settled so upgrading never invents payables
        db.execute("UPDATE purchases SET amount_paid_minor = total_minor")
    db.connect().executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_payments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id  INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            purchase_id  INTEGER REFERENCES purchases(id) ON DELETE SET NULL,
            amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
            method       TEXT,
            notes        TEXT,
            payment_date TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
            created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_suppay_supplier ON supplier_payments(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_suppay_date     ON supplier_payments(payment_date);
        """
    )
    log.info("Migration: added supplier payables (amount_paid + supplier_payments)")


def _migration_9_customers(db: Database) -> None:
    """v9: optional customer directory + purchase history. Adds the customers
    table and links sales to a customer (nullable; walk-in sales stay NULL)."""
    db.connect().executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            phone      TEXT    NOT NULL DEFAULT '',
            notes      TEXT,
            is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
            created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
            updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_name_phone
            ON customers(name COLLATE NOCASE, phone);
        CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
        """
    )
    if not _column_exists(db, "sales", "customer_id"):
        db.execute("ALTER TABLE sales ADD COLUMN customer_id INTEGER "
                   "REFERENCES customers(id) ON DELETE SET NULL")
    if not _column_exists(db, "sales", "customer_name"):
        db.execute("ALTER TABLE sales ADD COLUMN customer_name TEXT")
    log.info("Migration: added customers table + sales.customer link")


def _migration_10_ui_prefs(db: Database) -> None:
    """v10: UI preferences on company_settings — language (en/ur) and touch_mode
    (on-screen numeric keypad). Both default to the current behaviour."""
    if not _column_exists(db, "company_settings", "language"):
        db.execute("ALTER TABLE company_settings ADD COLUMN language TEXT "
                   "NOT NULL DEFAULT 'en'")
    if not _column_exists(db, "company_settings", "touch_mode"):
        db.execute("ALTER TABLE company_settings ADD COLUMN touch_mode INTEGER "
                   "NOT NULL DEFAULT 0")
    log.info("Migration: added company_settings.language + touch_mode")


def _migration_11_product_sort_order(db: Database) -> None:
    """v11: products.sort_order — a manual display order so the owner can arrange
    the product list to match a supplier's paper price sheet. Back-fill each
    existing product's order to its id, preserving the current (creation) order."""
    if not _column_exists(db, "products", "sort_order"):
        db.execute("ALTER TABLE products ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE products SET sort_order = id")
    log.info("Migration: added products.sort_order + back-filled to id")


def _migration_12_price_history(db: Database) -> None:
    """v12: product_price_history — log every price change so a price list can be
    reconstructed 'as of' a past date. Back-fill one baseline row per existing
    product using its CURRENT prices, effective from its created_at (we have no
    older data, so as-of dates before the first real change show today's price)."""
    db.connect().executescript(
        """
        CREATE TABLE IF NOT EXISTS product_price_history (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id           INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            purchase_price_minor INTEGER NOT NULL DEFAULT 0,
            sale_price_minor     INTEGER NOT NULL DEFAULT 0,
            changed_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
            changed_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pph_product ON product_price_history(product_id, changed_at);
        """
    )
    db.execute(
        "INSERT INTO product_price_history "
        "(product_id, purchase_price_minor, sale_price_minor, changed_at) "
        "SELECT id, purchase_price_minor, sale_price_minor, created_at FROM products p "
        "WHERE NOT EXISTS (SELECT 1 FROM product_price_history h WHERE h.product_id = p.id)")
    log.info("Migration: added product_price_history + baseline back-fill")


def _migration_13_customer_debt(db: Database) -> None:
    """v13: customer credit ('udhaar'). A Debt-method sale is unpaid and sits on
    the customer's tab; repayments live in customer_payments."""
    db.connect().executescript(
        """
        CREATE TABLE IF NOT EXISTS customer_payments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            sale_id      INTEGER REFERENCES sales(id) ON DELETE SET NULL,
            amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
            method       TEXT,
            notes        TEXT,
            payment_date TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
            created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_custpay_customer ON customer_payments(customer_id);
        CREATE INDEX IF NOT EXISTS idx_custpay_date     ON customer_payments(payment_date);
        """
    )
    log.info("Migration: added customer_payments (customer credit / debt)")


def _migration_14_custpay_account(db: Database) -> None:
    """v14: record WHICH account a debt repayment landed in (e.g. a specific
    EasyPaisa / bank account), mirroring how sales store the account."""
    if not _column_exists(db, "customer_payments", "account_id"):
        db.execute("ALTER TABLE customer_payments ADD COLUMN account_id INTEGER "
                   "REFERENCES payment_accounts(id) ON DELETE SET NULL")
    if not _column_exists(db, "customer_payments", "account_name"):
        db.execute("ALTER TABLE customer_payments ADD COLUMN account_name TEXT")
    log.info("Migration: added customer_payments.account_id + account_name")


def _migration_15_opening_debt(db: Database) -> None:
    """v15: opening balance a customer already owed on paper before going digital.
    Added to their balance_owed alongside on-system Debt sales."""
    if not _column_exists(db, "customers", "opening_debt_minor"):
        db.execute("ALTER TABLE customers ADD COLUMN opening_debt_minor "
                   "INTEGER NOT NULL DEFAULT 0")
    log.info("Migration: added customers.opening_debt_minor")


def _migration_18_product_packing(db: Database) -> None:
    """v18: structured packing so the catalog mirrors a manufacturer price list.

      * series           - product tier/line (e.g. Platinum, Gold, Fighter).
      * pack_size         - the pack the product is sold in (e.g. '1 L', '4 L').
      * units_per_carton  - how many packs make a full carton (>= 1); lets the
                            shop sell a whole carton in one action at POS.

    All nullable / defaulted so existing products are unaffected."""
    if not _column_exists(db, "products", "series"):
        db.execute("ALTER TABLE products ADD COLUMN series TEXT")
    if not _column_exists(db, "products", "pack_size"):
        db.execute("ALTER TABLE products ADD COLUMN pack_size TEXT")
    if not _column_exists(db, "products", "units_per_carton"):
        db.execute("ALTER TABLE products ADD COLUMN units_per_carton "
                   "INTEGER NOT NULL DEFAULT 1")
    log.info("Migration: products.series + pack_size + units_per_carton")


def _migration_19_drop_cash_drawer(db: Database) -> None:
    """v19: remove the cash-drawer feature. Drop its tables and the expense
    payment_method column (all expenses now come out of cash). Safe to re-run:
    DROP ... IF EXISTS is a no-op once gone."""
    db.connect().executescript(
        """
        DROP TABLE IF EXISTS cash_movements;
        DROP TABLE IF EXISTS cash_sessions;
        """
    )
    if _column_exists(db, "expenses", "payment_method"):
        try:
            db.execute("ALTER TABLE expenses DROP COLUMN payment_method")
        except Exception:
            # DROP COLUMN needs SQLite >= 3.35. If unavailable, leave it — it is
            # unused (all expenses are cash) and harmless.
            log.warning("Could not drop expenses.payment_method (SQLite too old?); "
                        "leaving it in place - it is unused and harmless.")
    log.info("Migration: dropped cash_sessions/cash_movements + expenses.payment_method")
