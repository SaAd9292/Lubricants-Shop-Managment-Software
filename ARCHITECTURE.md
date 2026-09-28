# Penguix — Architecture

> Package name: `lubripos`. Product name: **Penguix** — a white-label,
> single-tenant desktop POS + inventory + accounting system for lubricant and
> auto-parts shops. One installation == one shop. This document is the map for
> engineers who will maintain or extend the system.

---

## 1. What it is, in one paragraph

Penguix is an offline-first Windows desktop application (Python 3 + PySide6/Qt)
backed by a single local SQLite database. It has no server and no network
dependency for its core work — a shop runs it on one PC. Everything the shop
needs (products, suppliers, purchases with payables, sales with discounts and
returns, customers with credit/"udhaar" ledgers, expenses, cash-in-hand,
reports, users/permissions, backups) lives in that one database. The only
network features are an optional, cryptographically-signed **auto-update** and
nothing else. Shop identity (name, logo, currency, tax) is entirely
data-driven, so the same binary serves any shop with no code changes.

---

## 2. Technology and top-level layout

| Concern | Choice |
| --- | --- |
| Language | Python 3 (dev on 3.14, ships frozen via PyInstaller) |
| GUI | PySide6 (Qt 6) |
| Storage | SQLite (single file in the OS app-data dir) |
| PDF | ReportLab |
| Excel | openpyxl |
| Crypto | stdlib `hashlib` (PBKDF2) + a small pure-Python Ed25519 for update signatures |
| Packaging | PyInstaller one-file exe + Inno Setup installer |

```
lubripos/
  app_context.py      # composition root: builds db + shared services
  config.py           # paths (db, data_root) per-OS
  main.py (repo root) # entry point: init db -> login -> main window

  core/               # framework-agnostic primitives (no Qt, no SQL of their own)
    money.py          #   integer minor-unit money + formatting
    session.py        #   the signed-in user + permission checks (process-global)
    permissions.py    #   permission catalog + role defaults
    security.py       #   PBKDF2 password hash/verify
    ed25519.py        #   signature verify (+ keygen for the release tool)
    exceptions.py     #   LubriPosError hierarchy
    i18n.py           #   English/Urdu tr() dictionary
    packs.py          #   carton/pack quantity split helpers
    logging_config.py #   rotating file logger; documents "never log secrets"

  database/
    connection.py     # Database wrapper: connect, query, execute, transaction()
    schema.sql        # CREATE TABLE IF NOT EXISTS (base shape only)
    migrations.py     # idempotent, versioned ALTERs for existing DBs
    seed.py           # first-run seed (admin user, default categories/brands)
    db.py             # init_database(): schema -> migrations -> (seed via app_context)

  services/           # business logic + ALL SQL. One service per domain.
  controllers/        # thin adapters: permission gate + (ok, msg, data) tuples
  views/              # PySide6 screens and dialogs (the only Qt-aware layer besides ui/)
  ui/                 # reusable Qt widgets, theme tokens, toast, icons, keypad
  reports/            # report dict -> PDF/Excel; invoice + payment receipt PDFs
  models/             # (essentially empty — see §4)
```

---

## 3. Layered architecture and the golden rules

Data flows **down** through four layers and results flow **up**. Each layer may
only call the layer directly below it.

```
  View  (PySide6)                 user intent, rendering, no business rules
    |  calls controller methods, gets (ok, msg, data)
    v
  Controller                      permission gate + unit conversion + error->message
    |  calls one or more services
    v
  Service                         business rules + validation + SQL (the source of truth)
    |  uses the shared Database + AuditService
    v
  Database (SQLite)               storage
```

Golden rules, enforced by convention (there is no framework police — respect them):

1. **All SQL lives in services.** Controllers and views never touch the database.
   The one pragmatic exception is a handful of read-only display queries inside a
   couple of view dialogs; new code should not add more.
2. **Money is always integer minor units** (paisa/cents) end to end. Never floats
   in storage or math. `core/money.py` converts to/from the decimals the UI shows
   (`to_minor`, `format_money`). `currency_minor_units` (default 100) is per-shop.
3. **Controllers return `(ok: bool, msg: str, data)`.** Views branch on `ok` and
   show `msg` on failure. Controllers translate exceptions into human messages;
   they never leak a traceback to the UI.
4. **Permissions are checked in the controller**, via `core/session.py` helpers
   (`require_authenticated`, `require_role("admin")`, `require_permission("...")`).
   The sidebar only *shows* what a user may open; the controller is the real gate.
5. **The database is the single source of truth for derived numbers.** Balances
   (cash in hand, customer debt, supplier payables) are *computed from movements*,
   never stored as mutable counters — so they can't drift and are auditable.

---

## 4. The "M" in MVC

`models/` is intentionally almost empty. Domain records are passed around as
plain `dict`s (a row from SQLite via `sqlite3.Row` -> `dict`). This is a
deliberate simplification for a small app: services return dicts/lists of dicts,
controllers pass them up, views read keys. There is no ORM and no row-object
layer. If the app grows, the natural next step is typed dataclasses returned by
services — but that is not present today, so don't look for it.

---

## 5. Composition root: `AppContext`

`AppContext` (in `app_context.py`) is built once at startup and threaded into
every controller and view. It owns the shared, long-lived objects:

```
ctx.config    # Config: db_path, data_root
ctx.db        # Database (one SQLite connection wrapper, main thread)
ctx.audit     # AuditService (writes audit_logs)
ctx.auth      # AuthService (login, change password)
ctx.company   # CompanyService (shop identity + tax settings, cash opening float)
ctx.backup    # BackupService (backup / restore / flush)
```

Every controller takes `ctx` and constructs the domain services it needs from
`ctx.db` and `ctx.audit`. Services are cheap and stateless, so they're created
per-controller rather than cached — don't add global service singletons.

**Threading note:** the SQLite connection is bound to the main thread. The
auto-update check runs on a background thread and therefore must **not** touch
`ctx.db` — it persists its throttle/pending state to small files under
`data_root` instead. Keep any future background work off the shared connection.

---

## 6. Database

### 6.1 How the schema is applied (every startup)

`init_database()` runs, in order, on every launch:

1. `schema.sql` via `executescript` — `CREATE TABLE IF NOT EXISTS` for the base
   shape. This never alters an existing table.
2. `run_migrations(db)` — a fixed list of idempotent migration functions.
3. `seed` (through app_context) — creates the default admin and default
   categories/brands only if missing.

### 6.2 Migrations (`database/migrations.py`)

`CURRENT_VERSION` is the schema version (currently **28**). `run_migrations`
calls each `_migration_N_*` function unconditionally; each one is **idempotent**
— it checks current state (via `_column_exists`, or reading `sqlite_master`)
before acting, so running them on every startup is safe and a brand-new DB and a
years-old DB converge to the same shape.

Two migration patterns are used:

- **Add a column:** `if not _column_exists(...): ALTER TABLE ... ADD COLUMN`.
  This is the common case. Note: newer columns live *only* in migrations, not in
  `schema.sql` — a fresh DB gets them because migrations run right after the
  base schema. When adding a column, add a migration; you do not need to edit
  `schema.sql`.
- **Change a constraint (drop NOT NULL / CHECK):** SQLite can't `ALTER` a
  constraint, so these migrations rebuild the table: read its `sqlite_master`
  SQL, regex-edit the definition, create `<table>_new`, `INSERT ... SELECT`,
  drop the old, rename, and recreate indexes — all with
  `PRAGMA foreign_keys=OFF` around the swap. See `_migration_24` (allow negative
  stock) and `_migration_27` (nullable `sale_returns.sale_id`) for the template.

**When you add a migration:** bump `CURRENT_VERSION`, append the call in
`run_migrations`, and write the function idempotently. Never renumber or reorder
existing migrations.

### 6.3 Tables (23)

| Table | Purpose |
| --- | --- |
| `app_meta` | key/value; holds `schema_version` |
| `users` | login accounts: `password_hash`/`password_salt`/`pwd_iterations`, `role`, `permissions`, `must_change_pw` |
| `company_settings` | the white-label row (id=1): shop name, logo blob, currency, invoice prefix/footer, theme, language, **cash opening float + date** |
| `tax_settings` | single row: enabled, label, rate (bps), inclusive |
| `categories`, `brands` | product taxonomy (soft-deletable) |
| `products` | catalog: prices (minor), `stock_qty` (may be negative), min level, pack sizes, sort order |
| `product_price_history` | append-only price-change log |
| `suppliers` | supplier directory + opening payable |
| `purchases`, `purchase_items` | stock in; header carries bill discount + `amount_paid` (the rest is a payable) |
| `supplier_payments` | payments settling supplier payables |
| `payment_accounts` | named Bank / EasyPaisa / JazzCash accounts |
| `customers` | customer directory + opening debt |
| `customer_payments` | debt repayments / recoveries (method + account) |
| `sales`, `sale_items` | sales; header carries bill discount, tax, payment method/account, notes |
| `sale_returns`, `sale_return_items` | returns; `sale_id` nullable (no-receipt returns), `method` = refund channel |
| `expense_categories`, `expenses` | expenses |
| `backups` | backup file registry |
| `audit_logs` | who did what, when (append-only) |

Money columns end in `_minor`. Timestamps are `TEXT` `'YYYY-MM-DD HH:MM:SS'`;
date-range queries compare on the 10-char date prefix.

---

## 7. Money, and why derived balances

`core/money.py` is the only place that knows how minor units map to display
decimals. Rules of thumb: multiply/subtract in minor units as plain ints;
convert at the UI boundary only.

Three "balances" are **derived on read**, never stored:

- **Customer debt (`balance_owed`)** = opening debt + unpaid credit sales −
  repayments. (`customer_service.balance_owed`)
- **Supplier payable** = Σ(purchase totals − amount paid) − supplier payments.
  (`payable_service` / `supplier` ledger)
- **Cash in Hand** = opening float + cash movements since the float's "as-of"
  date. (`services/cash_service.py`, see §9)

This is the single most important design decision in the app: a stored running
total drifts the instant anything is edited, deleted, or back-dated. Deriving
from the movement tables makes every balance reproducible and auditable, at the
cost of a few SUMs per read (fine at shop data volumes).

---

## 8. Key data flows

### 8.1 Sale (live POS)

```
POSView -> SaleController.checkout(lines, discount, payment_method, account, amount_paid, notes, allow_oversell)
        -> SaleService.create_sale(...)  [inside one transaction]
             validate lines, resolve prices, apply per-line + bill discounts, compute tax
             INSERT sales + sale_items
             UPDATE products.stock_qty -= qty     (may go negative if allow_oversell)
             audit "SALE_CREATE"
        -> returns summary (invoice_no, totals, short_lines)
POSView -> optional invoice PDF via InvoiceService -> invoice_pdf.py
```

Oversell: stock is allowed to go **negative** (goods sold from the distribution
warehouse before the purchase is booked). The POS asks the cashier to confirm;
back-dated entry allows it silently and flags short lines. Negative stock nets
back up when the matching purchase is entered.

### 8.2 Back-dated sale (admin data entry)

`BackdateEntryView` -> `SaleController.record_backdated_sale(...)` — same
`create_sale`, but stamped on a chosen past date, admin-only, never blocks on
short stock. Used to migrate a paper backlog quickly.

### 8.3 Purchase

`NewPurchaseDialog` -> `PurchaseController.create(...)` ->
`PurchaseService.create_purchase(...)`: INSERT purchase + items, **increase
stock**, set each product's cost basis to the discounted per-unit cost, apply
markup to suggest a new sale price, and record `amount_paid` (remainder becomes
a supplier payable). Admin can `delete_purchase` (password-gated; reverses stock
and payable, blocked if the stock was already sold).

### 8.4 Return (with or without receipt)

- **With receipt:** `ReturnsView` looks up the invoice ->
  `SaleController.create_return(sale_id, lines)` -> restores stock, records the
  refund, caps each line at what's still returnable.
- **No receipt:** `NoReceiptReturnDialog` ->
  `SaleController.create_no_receipt_return(lines, method, notes)` -> an
  *unlinked* return (`sale_returns.sale_id = NULL`), operator sets the refund
  amount and channel. Restores stock. Gated by the void/return privilege.

Cash-method refunds reduce Cash in Hand; bank/wallet refunds don't.

### 8.5 Customer debt & Cash Recovery

Credit ("udhaar") sales sit on the customer's tab. Repayments are recorded via
the **Cash Recovery** sidebar screen (`CashRecoveryView` ->
`CustomerController.record_payment`), which prints a receipt
(`payment_receipt_pdf.py`). The customer **Ledger** dialog is a read-only
Debit/Credit/Balance book (charges = debit, payments = credit) and is printable
via the generic report exporter. It is separate from **Purchase history** (what
they bought).

### 8.6 Reports

Every report is a **plain dict** built by `services/report_service.py`
(`{key, title, subtitle, columns, rows, summary, layout, orientation}`), then
handed to `reports/report_exporter.py` which renders any such dict to PDF
(ReportLab) or Excel (openpyxl). Three layouts: flat table, `day_close` (the
DSR), and `sections`. On-screen the same dict feeds `DayCloseWidget` /
`report_sections_widget`. Adding a report = add a builder method + a
`ReportController.build` route + a row in `reports_view.REPORTS`. No exporter
changes needed for a flat table.

### 8.7 Auth & session

`LoginDialog` -> `AuthController.login` -> `AuthService`: PBKDF2 verify
(constant-time), generic failure message (no user-enumeration), audited. On
success, `core/session.current_session` holds the `CurrentUser` (id, role,
permissions) process-wide; controllers read it for gating. `must_change_pw`
forces a password change on first login of the seeded admin.

### 8.8 Auto-update (the only network feature)

Background thread -> `UpdateService.check()`:

1. Fetch `latest.json` from GitHub Releases over verified HTTPS (certifi CA in
   the frozen build).
2. **Verify the Ed25519 signature** over the canonical `data` before trusting
   anything. Reject on mismatch — so a compromised host still can't push a fake
   update.
3. If newer, download the installer and **verify its SHA-256** against the
   signed manifest; discard on mismatch.
4. Launch the Inno Setup installer (with `_PYI*`/`_MEIPASS` env vars stripped)
   and quit so files can be swapped. Migrations run on next launch.

The private signing seed lives only in `keys/` (gitignored) and in
`tools/release.py` at release time — never in the shipped app. Release tags
**must** be `v`-prefixed (`vX.Y.Z`) to match the manifest URL.

### 8.9 Backup & restore

`BackupService`: backups use SQLite's online backup API (consistent even
mid-write), registered in `backups`. Restore **validates** the chosen file
(`PRAGMA integrity_check` + expected tables) and takes a pre-restore safety
backup before overwriting. "Flush shop data" clears transactional tables (keeps
users/settings/taxonomy) behind an admin-password re-confirm, safety-backup
first.

---

## 9. Cash in Hand (the running drawer balance)

`services/cash_service.py` is the single source of truth. Balance at date *D* =
`cash_opening_minor` (set in Settings) + every cash movement dated on/after
`cash_opening_date` up to *D*:

```
+ cash sales            (sales.payment_method = Cash, completed)
+ cash debt repayments  (customer_payments, method Cash/NULL)
- cash refunds          (sale_returns, method Cash/NULL)
- expenses              (all expenses are cash out)
- purchase payments     (purchases.amount_paid — treated as cash from the till)
- supplier payments     (supplier_payments — treated as cash from the till)
```

Only cash-channel movements count; Bank/EasyPaisa/JazzCash never touch the
drawer. The **Cash in Hand Ledger** report (`report_service.cash_ledger`) lists
every movement with a running balance that closes exactly to
`balance_as_of(range end)` — that invariant is covered by `tests/test_cash_ledger.py`.

The opening float is a one-field baseline (`company_settings`). Re-baselining
(e.g. a quarterly count) means updating that field + as-of date; be aware this
single field does not preserve *past* baselines, so historical cash-ledger
ranges recompute from the latest float. (A baseline-history table is the planned
upgrade if past-period accuracy is required — see §12.)

---

## 10. UI conventions

- **Navigation:** `main_window.py` holds a sidebar (`NAV_ITEMS`) + a
  `QStackedWidget`. Selecting an item drills in full-width and hides the sidebar;
  a header "☰ Menu" button or **Esc** brings it back. Each page is built once and
  cached; `_go(key)` re-pulls its data via a `refresh()`/`_reload()` hook so
  screens never show stale snapshots. `F2` -> Sale, `Alt+1..9` -> first nine
  screens, from anywhere.
- **Theme:** `ui/theme.py` is token-driven light/dark; the choice persists in
  `company_settings.theme` and applies live.
- **Widgets:** shared table (`DataTable`), flow layout, toast, numeric keypad
  (touch mode), and a `WheelGuard` that blocks accidental mouse-wheel edits on
  spin/date/combo boxes. Money columns use tabular figures.
- **Dialog-style pages:** data-entry screens (Cash Recovery, Past-Date Sale) are
  centered fixed-width cards inside a scroll area.

---

## 11. Testing & verification

- `tests/` holds ~32 **headless** suites (no Qt) that exercise services and
  controllers directly, each printing `N/N checks passed`. They cover money math,
  discounts, negative stock, returns (incl. no-receipt), cash-in-hand and the
  cash ledger, payables, permissions, backup/restore, i18n, and reports.
- Qt cannot run in CI/sandbox here (no display/libEGL), so **views are verified
  by `py_compile` + `pyflakes`**, and their logic is exercised through the
  service/controller layer the view calls. Keep view code thin so this holds.
- Before shipping: run every `tests/test_*.py` (all must print a summary and exit
  0), `python -m compileall lubripos`, and `python -m pyflakes lubripos`.

---

## 12. Known gaps / planned work (for the next engineer)

- **Account settlement (wallet -> cash):** EasyPaisa/JazzCash accounts are staff
  personal wallets; a digital sale sits there until the staff member hands cash
  to the till at day end. A "settle to cash" flow (increments Cash in Hand,
  clears a per-account outstanding) is designed but not yet built.
- **Cash baseline history:** the opening float is a single field; a table of
  dated baselines would keep past-quarter cash ledgers accurate across resets.
- **No login lockout / rate-limiting:** brute force is only possible with local
  file access and is slowed by PBKDF2 (240k iters), but a lockout would be
  defense-in-depth.
- **DB is unencrypted at rest** (standard for a local POS; whoever has the file
  has the data). If a shop needs at-rest encryption, that's a SQLCipher-class
  change.
- **Password-reset scripts** (`reset_admin_password.py`, `reset_password.py`) are
  offline recovery tools that bypass auth by design. Keep them off shop machines
  or restrict to the owner; do not bundle them into the distributed installer.
- **Report controller doesn't re-check permissions** (the sidebar gates
  visibility). Harmless in a local single-process app, but add a
  `require_permission("reports")` if the app ever grows a remote surface.

---

## 13. Build & release (summary)

1. `build_exe.bat` -> `dist\Penguix.exe` (PyInstaller one-file).
2. `installer\build_installer.bat` (needs Inno Setup) ->
   `installer\output\Penguix-Setup-<version>.exe`.
3. `python tools\release.py --installer <that exe> --notes "..."` -> signs
   `dist\latest.json` with the private seed in `keys/`.
4. Publish a GitHub Release tagged **`vX.Y.Z`** with **both** the installer and
   `latest.json` as assets.

Version lives in `lubripos/__init__.py` (`__version__`) and
`installer/penguix_installer.iss` (`AppVersion`) — bump both together.
See `BUILD.md` for the long form.
