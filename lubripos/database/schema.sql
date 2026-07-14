-- =====================================================================
-- LubriPOS — SQLite schema (white-label, single-tenant per installation)
-- =====================================================================
-- DESIGN RULES (enforced throughout):
--   * All money is stored as INTEGER "minor units" (e.g. paisa/cents).
--     Never use REAL/FLOAT for currency. Format to decimal at the UI layer.
--   * Tax rates are stored as INTEGER "basis points" (bps): 17.00% = 1700.
--   * No hard deletes on entities referenced by history (products, users):
--     use is_active = 0 (soft delete). FK integrity is preserved.
--   * Sales/purchase line items SNAPSHOT name/price/cost at transaction time
--     so historical documents never change when a product is later edited.
--   * Timestamps are ISO-8601 TEXT in UTC ('YYYY-MM-DD HH:MM:SS').
--   * Singleton config tables are pinned to id = 1 via CHECK.
-- Pragmas (foreign_keys, journal_mode=WAL) are set per-connection in code.
-- =====================================================================

-- ---------- Schema versioning (for future migrations) ----------------
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------- Users / authentication -----------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT,
    password_hash TEXT    NOT NULL,          -- PBKDF2-HMAC-SHA256 (hex)
    password_salt TEXT    NOT NULL,          -- per-user random salt (hex)
    pwd_iterations INTEGER NOT NULL DEFAULT 240000,
    role          TEXT    NOT NULL CHECK (role IN ('admin','cashier')),
    must_change_pw INTEGER NOT NULL DEFAULT 0 CHECK (must_change_pw IN (0,1)),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    permissions   TEXT,                       -- JSON array of granted keys (non-admins)
    last_login_at TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- ---------- Company / shop identity (white-label core) ---------------
CREATE TABLE IF NOT EXISTS company_settings (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    shop_name     TEXT    NOT NULL DEFAULT 'My Shop',
    owner_name    TEXT,
    phone         TEXT,
    email         TEXT,
    address       TEXT,
    logo_path     TEXT,
    ntn_number    TEXT,
    gst_number    TEXT,
    currency_code TEXT    NOT NULL DEFAULT 'PKR',   -- ISO 4217-ish code
    currency_symbol TEXT  NOT NULL DEFAULT 'Rs',
    currency_minor_units INTEGER NOT NULL DEFAULT 100, -- 100 = 2 decimals
    invoice_prefix TEXT   NOT NULL DEFAULT 'INV',
    invoice_footer TEXT   NOT NULL DEFAULT 'Thank you for your business!',
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- ---------- Tax configuration (single source of truth) ---------------
-- NOTE: the original spec listed tax_percentage on company_settings AND a
-- separate tax_settings table. Storing tax in two places invites drift, so
-- tax lives ONLY here. Rate is basis points (1700 = 17.00%).
CREATE TABLE IF NOT EXISTS tax_settings (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    tax_enabled  INTEGER NOT NULL DEFAULT 1 CHECK (tax_enabled IN (0,1)),
    tax_label    TEXT    NOT NULL DEFAULT 'GST',
    tax_rate_bps INTEGER NOT NULL DEFAULT 0 CHECK (tax_rate_bps >= 0),
    tax_inclusive INTEGER NOT NULL DEFAULT 0 CHECK (tax_inclusive IN (0,1)),
    updated_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- ---------- Product taxonomy -----------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS brands (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- ---------- Products --------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode             TEXT UNIQUE,           -- manufacturer barcode; NULL allowed
    name                TEXT    NOT NULL,
    brand_id            INTEGER REFERENCES brands(id)     ON DELETE SET NULL,
    category_id         INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    unit_type           TEXT    NOT NULL DEFAULT 'Piece'
                            CHECK (unit_type IN ('Piece','Bottle','Carton','Litre','Kg')),
    purchase_price_minor INTEGER NOT NULL DEFAULT 0 CHECK (purchase_price_minor >= 0),
    sale_price_minor     INTEGER NOT NULL DEFAULT 0 CHECK (sale_price_minor >= 0),
    -- Markup over cost in basis points (2000 = 20%). When > 0, the sale price is
    -- auto-derived as cost*(1+markup) on every purchase. 0 = manual pricing
    -- (sale price is never auto-changed).
    markup_bps          INTEGER NOT NULL DEFAULT 0 CHECK (markup_bps >= 0),
    stock_qty           INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    min_stock_level     INTEGER NOT NULL DEFAULT 0 CHECK (min_stock_level >= 0),
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_products_barcode  ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_name     ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_brand    ON products(brand_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_active   ON products(is_active);

-- ---------- Suppliers -------------------------------------------------
CREATE TABLE IF NOT EXISTS suppliers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    phone      TEXT,
    address    TEXT,
    notes      TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

-- ---------- Purchases (stock in) -------------------------------------
CREATE TABLE IF NOT EXISTS purchases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id   INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    supplier_invoice_no TEXT,                 -- supplier's own reference
    purchase_date TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    total_minor   INTEGER NOT NULL DEFAULT 0 CHECK (total_minor >= 0),
    -- how much of `total_minor` was paid at purchase time; the remainder is a
    -- payable owed to the supplier. Later payments live in supplier_payments.
    amount_paid_minor INTEGER NOT NULL DEFAULT 0 CHECK (amount_paid_minor >= 0),
    notes         TEXT,
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_purchases_date     ON purchases(purchase_date);
CREATE INDEX IF NOT EXISTS idx_purchases_supplier ON purchases(supplier_id);

-- Payments made to a supplier AFTER the purchase (settling payables). The
-- supplier balance = SUM(purchases.total - amount_paid) - SUM(these payments).
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

CREATE TABLE IF NOT EXISTS purchase_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id     INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    qty             INTEGER NOT NULL CHECK (qty > 0),
    unit_cost_minor INTEGER NOT NULL CHECK (unit_cost_minor >= 0),
    line_total_minor INTEGER NOT NULL CHECK (line_total_minor >= 0)
);
CREATE INDEX IF NOT EXISTS idx_pitems_purchase ON purchase_items(purchase_id);
CREATE INDEX IF NOT EXISTS idx_pitems_product  ON purchase_items(product_id);

-- ---------- Payment accounts (named Bank / EasyPaisa / JazzCash) -----
CREATE TABLE IF NOT EXISTS payment_accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    method       TEXT    NOT NULL CHECK (method IN ('Bank','EasyPaisa','JazzCash')),
    name         TEXT    NOT NULL,
    account_no   TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_payacct_method ON payment_accounts(method);

-- ---------- Sales (stock out / invoices) -----------------------------
CREATE TABLE IF NOT EXISTS sales (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no       TEXT    NOT NULL UNIQUE,
    sale_date        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    cashier_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    cashier_name     TEXT,                       -- snapshot
    subtotal_minor   INTEGER NOT NULL DEFAULT 0 CHECK (subtotal_minor >= 0),
    discount_minor   INTEGER NOT NULL DEFAULT 0 CHECK (discount_minor >= 0),
    tax_label        TEXT    NOT NULL DEFAULT 'GST',   -- snapshot
    tax_rate_bps     INTEGER NOT NULL DEFAULT 0,       -- snapshot
    tax_minor        INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    grand_total_minor INTEGER NOT NULL DEFAULT 0 CHECK (grand_total_minor >= 0),
    payment_method   TEXT    NOT NULL DEFAULT 'cash',
    payment_account_id   INTEGER REFERENCES payment_accounts(id) ON DELETE SET NULL,
    payment_account_name TEXT,                       -- snapshot (survives account delete)
    amount_paid_minor INTEGER NOT NULL DEFAULT 0,
    status           TEXT    NOT NULL DEFAULT 'completed'
                         CHECK (status IN ('completed','void')),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_sales_date    ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_cashier ON sales(cashier_id);
CREATE INDEX IF NOT EXISTS idx_sales_status  ON sales(status);

CREATE TABLE IF NOT EXISTS sale_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id          INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id       INTEGER REFERENCES products(id),  -- nullable: product may be retired
    product_name     TEXT    NOT NULL,                 -- snapshot
    barcode          TEXT,                             -- snapshot
    qty              INTEGER NOT NULL CHECK (qty > 0),
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    unit_cost_minor  INTEGER NOT NULL DEFAULT 0,       -- snapshot cost for profit calc
    returned_qty     INTEGER NOT NULL DEFAULT 0 CHECK (returned_qty >= 0),  -- partial returns
    line_total_minor INTEGER NOT NULL CHECK (line_total_minor >= 0)
);
CREATE INDEX IF NOT EXISTS idx_sitems_sale    ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sitems_product ON sale_items(product_id);

-- ---------- Returns / refunds ledger (partial or full) ---------------
-- Each return records which invoice, which items and quantities came back,
-- and the refunded amount. Stock is restored and sale_items.returned_qty is
-- bumped so a line can never be over-returned. Sales stay 'completed'; reports
-- net returns out via this ledger (Net = gross sales - refunds).
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
    product_name     TEXT    NOT NULL,                 -- snapshot
    qty              INTEGER NOT NULL CHECK (qty > 0),
    unit_price_minor INTEGER NOT NULL,
    unit_cost_minor  INTEGER NOT NULL DEFAULT 0,       -- snapshot for profit netting
    line_total_minor INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ritems_return ON sale_return_items(return_id);

-- ---------- Expenses --------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    category     TEXT    NOT NULL,                 -- free text, defaults from lookup
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    description  TEXT,
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_expenses_date     ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category);

-- ---------- Backups registry -----------------------------------------
CREATE TABLE IF NOT EXISTS backups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT    NOT NULL,
    file_size_bytes INTEGER,
    backup_type     TEXT    NOT NULL DEFAULT 'manual'
                        CHECK (backup_type IN ('auto','manual','pre_restore')),
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- ---------- Audit log (append-only) ----------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username    TEXT,                              -- snapshot
    action      TEXT    NOT NULL,                  -- LOGIN, CREATE, UPDATE, DELETE, SALE, ...
    entity_type TEXT,                              -- product, sale, purchase, user, ...
    entity_id   INTEGER,
    details     TEXT,                              -- JSON: before/after or context
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_entity  ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_user    ON audit_logs(user_id);

-- ---------- updated_at maintenance triggers --------------------------
CREATE TRIGGER IF NOT EXISTS trg_users_updated
    AFTER UPDATE ON users FOR EACH ROW
BEGIN
    UPDATE users SET updated_at = strftime('%Y-%m-%d %H:%M:%S','now') WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_products_updated
    AFTER UPDATE ON products FOR EACH ROW
BEGIN
    UPDATE products SET updated_at = strftime('%Y-%m-%d %H:%M:%S','now') WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_suppliers_updated
    AFTER UPDATE ON suppliers FOR EACH ROW
BEGIN
    UPDATE suppliers SET updated_at = strftime('%Y-%m-%d %H:%M:%S','now') WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_company_updated
    AFTER UPDATE ON company_settings FOR EACH ROW
BEGIN
    UPDATE company_settings SET updated_at = strftime('%Y-%m-%d %H:%M:%S','now') WHERE id = OLD.id;
END;

