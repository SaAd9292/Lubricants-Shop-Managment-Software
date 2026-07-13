# How Penguix Was Built
### A complete technical account of the LubriPOS (Penguix) desktop application

---

## 1. What Penguix is

Penguix is a **white-label, offline desktop Point-of-Sale, inventory, and
accounting system** built for lubricant shops, auto-parts stores, and small
automotive retailers. One installation serves one shop, but the *same* software
works for any shop — nothing about a business is hard-coded. The shop name,
logo, address, tax numbers, currency, and tax rate all come from a settings
table, so the app can be sold to many businesses unchanged.

It runs entirely on a single Windows PC with a **local SQLite database** — no
server, no internet, no cloud dependency. That makes it fast, private, and
reliable for a shop counter that may not have stable connectivity.

**What it does, at a glance**

- Point of sale with barcode scanning, cart, discounts, and printed receipts.
- Product catalogue with brands, categories, stock levels, and markup pricing.
- Purchasing (stock in) from suppliers, which raises stock automatically.
- Sales history with the ability to **void / reverse** a completed sale.
- Expenses tracking, and named payment accounts (Cash / Bank / EasyPaisa / JazzCash).
- Eight reports, including a grid-style **Day-Close** report and monthly analysis.
- Multi-user access with an admin and per-user privileges for cashiers.
- Automatic and manual backups, restore, and a full audit log.

---

## 2. Technology stack (and why)

| Layer | Technology | Why it was chosen |
|---|---|---|
| Language | **Python 3.13+** | Fast to develop, huge ecosystem, easy to maintain. |
| Desktop UI | **PySide6 (Qt 6)** | Native-looking Windows widgets, mature, no web stack needed. |
| Database | **SQLite** (WAL mode) | Zero-config, single file, transactional, perfect for one-PC offline use. |
| PDF documents | **ReportLab** | Precise control over invoices/receipts and report layout. |
| Excel export | **OpenPyXL** | Native `.xlsx` output for reports. |
| Packaging | **PyInstaller** + **Inno Setup** | Bundles Python + Qt into one `.exe` and a Windows installer. |

Deliberately **excluded**: any web framework, ORM, cloud service, or heavyweight
data library (numpy/pandas). The app is intentionally lean so the packaged exe
stays small and starts quickly.

---

## 3. Architecture: MVC + a service layer

Penguix uses a **four-layer** architecture. Each layer only talks to the one
below it, which keeps business rules out of the UI and makes everything testable
without a screen.

```
   Views (PySide6)        "What the user sees and clicks"
        |  calls, receives (ok, message, data)
        v
   Controllers            "Guard permissions, convert money, map errors"
        |  calls services with clean values
        v
   Services               "ALL business logic + ALL SQL"
        |  parameterised queries
        v
   Database               "connection, schema, migrations"
```

**Views** (`lubripos/views/`) are pure Qt. They never contain SQL and never make
business decisions. They collect input, call a controller, and render whatever
comes back.

**Controllers** (`lubripos/controllers/`) are the seam between UI and logic.
They:
- check the current user's role / privileges before privileged actions,
- convert decimal money typed by the user into integer "minor units",
- catch domain errors and return a uniform `(ok: bool, message: str, data)`
  tuple so views can show a friendly message instead of a stack trace.

**Services** (`lubripos/services/`) hold *all* business logic and *all*
database access. A sale's atomic transaction, tax snapshotting, stock
decrements, backup logic, report queries — they all live here. Because services
take a database handle and nothing Qt-related, every one of them is tested
headlessly.

**Database** (`lubripos/database/`) is the connection manager, the `schema.sql`
that defines every table, and the idempotent migration runner.

**The composition root** is `AppContext` (`lubripos/app_context.py`). It builds
the long-lived objects once at startup (config → database → core services) and
hands them to the UI. This dependency-injection style avoids global singletons
for data and keeps services swappable in tests.

---

## 4. Project structure

```
Lubricants Shop Software/
├─ main.py                     # entry point: builds AppContext, shows login, runs Qt loop
├─ penguix.spec                # PyInstaller build recipe (bundles schema.sql + assets)
├─ build_exe.bat               # one-click: run PyInstaller
├─ installer/                  # Inno Setup script + build_installer.bat
├─ assets/                     # penguix.png (sidebar logo) + penguix.ico (window icon)
├─ requirements.txt
├─ tests/                      # 14 headless test suites (no GUI needed)
└─ lubripos/                   # the application package
   ├─ app_context.py           # composition root (wires everything)
   ├─ config.py                # paths, %APPDATA% data dir, resource_path()
   ├─ core/                    # cross-cutting helpers (money, session, permissions, security, logging)
   ├─ database/                # connection.py, schema.sql, migrations.py, db.py, seed.py
   ├─ models/                  # lightweight data holders
   ├─ services/                # business logic + SQL (product, sale, purchase, report, backup, user, ...)
   ├─ controllers/             # permission guards + money conversion + error mapping
   ├─ reports/                 # invoice_pdf.py (80mm receipt) + report_exporter.py (PDF/Excel)
   ├─ ui/                      # theme, reusable widgets, icons
   └─ views/                   # every screen + dialog (PySide6)
```

Runtime data does **not** live in the program folder. The database, logs, and
backups live under `%APPDATA%\Penguix` so an app update never touches shop data.

---

## 5. The data model

### 5.1 Money is always an integer

The single most important data decision: **money is never stored as a floating
point number.** Every amount is an INTEGER number of "minor units" (paisa) —
e.g. `Rs 1,500.00` is stored as `150000`. This eliminates rounding errors that
plague float-based money maths. Decimal values are only produced at the very
edge (the UI and printed documents) by `core/money.py`.

Similarly, **tax rates are integer "basis points"**: 18.00% is stored as `1800`.

### 5.2 Snapshots keep history correct

When a sale or purchase line is created, the product's name, barcode, unit
price, and unit cost are **copied onto the line** (`sale_items`,
`purchase_items`). If a product is later renamed, repriced, or retired, every
historical invoice and every profit figure stays exactly as it was at the time
of sale. History never silently changes.

### 5.3 Soft deletes protect referential integrity

Products, suppliers, categories, brands, and users are never hard-deleted while
they have history — they are marked `is_active = 0` (deactivated). They vanish
from lists and the POS but their past transactions remain intact. Where a hard
delete is offered (users, payment accounts) the foreign keys use
`ON DELETE SET NULL` and a name snapshot is kept, so invoices still show who
rang them up and which account received the money.

### 5.4 Core tables

`users`, `company_settings`, `tax_settings`, `categories`, `brands`,
`products`, `suppliers`, `purchases`, `purchase_items`, `payment_accounts`,
`sales`, `sale_items`, `expenses`, `backups`, `audit_logs`, and `app_meta`
(which stores the schema version and the invoice counter).

### 5.5 Migrations

`schema.sql` uses `CREATE TABLE IF NOT EXISTS`, so it never disturbs an existing
database. Anything that must change on an already-installed database goes into
`migrations.py` as a small, **idempotent** function that checks state before
acting. The latest applied version is recorded in `app_meta.schema_version`, and
every migration is safe to run on every startup. The versions so far:

- **v2** removed the unused product-image column.
- **v3** relaxed the backups table to allow the safety-backup type.
- **v4** added markup-over-cost pricing and back-filled implied markups.
- **v5** added named payment accounts and linked each sale to its account.
- **v6** added per-user privileges and back-filled existing cashiers with a
  sensible default so nobody loses access on upgrade.

---

## 6. Cross-cutting core

- **`core/money.py`** — the only place decimals meet integers: `to_minor`,
  `from_minor`, `format_money`, `apply_tax` (inclusive/exclusive), `apply_markup`.
- **`core/session.py`** — the currently logged-in user and the access checks:
  `require_role`, `can(permission)`, `require_permission`. Checks live in code,
  not just in hidden buttons.
- **`core/permissions.py`** — the catalogue of grantable **screens** and
  **actions**, plus JSON (de)serialisation of a user's grant list.
- **`core/security.py`** — password hashing with **PBKDF2-HMAC-SHA256** and a
  per-user random salt. Plain passwords are never stored.
- **`core/logging_config.py`** — structured logging to a rotating file under
  `%APPDATA%\Penguix\logs`, so problems can be diagnosed after deployment.
- **`core/exceptions.py`** — a small hierarchy (`ValidationError`,
  `NotFoundError`, `AuthError`, `PermissionDenied`, `InsufficientStockError`)
  that controllers translate into friendly messages.
- **`config.py`** — resolves data/log/backup folders and `resource_path()`,
  which finds bundled files whether running from source or from the packaged exe.

---

## 7. Module-by-module tour

**Dashboard** — KPI cards (today's sales, profit, expenses, stock value, low-stock
alerts, inactive products) plus Recent Sales and Low Stock lists. Cards are
clickable shortcuts into the relevant screen.

**Sale (POS)** — scan a barcode (a USB scanner acts as a keyboard), the product
drops into the cart instantly; adjust quantity and (if permitted) price; set a
discount and payment method/account; press **Complete Sale (F2)**. Quantity is
capped at available stock so the cart can never oversell.

**Sales History** — searchable, date-filterable list of every invoice, with view /
reprint (PDF), and **Void / reverse a sale** — which restores stock and marks the
invoice void while keeping it for audit.

**Products** — searchable, sortable, paginated catalogue with brand/category
filters, low-stock tinting, stock adjustment, and activate/deactivate. Markup
pricing can auto-derive a sale price from cost on each purchase.

**Categories & Brands, Suppliers** — simple maintained lists used across the app.

**Purchases** — record stock coming in from a supplier; multiple products per
purchase; stock rises automatically and (optionally) sale prices are recomputed
from the new cost via each product's markup.

**Expenses** — day-to-day outgoings by category, searchable and date-filterable,
feeding the Day-Close and Expense reports.

**Reports** — eight reports sharing one engine: Daily Sales (a grid **Day-Close**
sheet: every sale line, expenses, and money received per account), Monthly Sales
(by day + by product), Profit, Stock, Low Stock, Purchases (itemised), Expenses,
and GST/Tax. All export to PDF and Excel and print.

**Settings** — the white-label control centre: shop identity, currency/invoice,
GST on/off + rate, payment-account management, and a guarded "Danger Zone" flush.

**Users** — accounts and, for cashiers, the per-user privilege checkboxes.

**Backup & Restore** and **Audit Log** — data safety and an append-only trail of
who did what.

---

## 8. Key workflows

**A sale, end to end.** The cashier builds a cart in the view. On checkout the
controller converts prices/discount to minor units and checks permissions, then
`SaleService.create_sale` runs everything as **one atomic SQLite transaction**:
validate each line (active product, quantity, enough stock) → snapshot
name/price/cost onto each line → apply discount and snapshot the live tax
settings → allocate the next sequential invoice number → insert the sale and its
items → decrement stock. If anything fails (e.g. insufficient stock) the whole
transaction rolls back: no invoice, no stock movement. An audit entry is written
and a receipt is offered.

**Reversing a sale.** Voiding runs its own transaction that adds the sold
quantities back to stock and flips the sale's status to `void`. The sale is kept
(never hard-deleted) so the audit trail and invoice numbering stay intact.

**A purchase.** Recording a purchase inserts the purchase and its lines and adds
the quantities to product stock, optionally re-deriving sale prices from the new
cost using each product's markup.

**Backup / restore.** Backups use SQLite's **online-backup API**, producing a
consistent snapshot even mid-write (never a raw file copy of a live WAL
database). Restore is destructive, so it first takes a `pre_restore` safety
backup, validates the chosen file (integrity check + required tables), then
swaps it in. Daily auto-backups run once per day and old ones are pruned.

---

## 9. Security model

- **Passwords**: PBKDF2-HMAC-SHA256 with a per-user salt; never stored in plain
  text; new users must change their password on first login.
- **Access control**: two roles (admin, cashier). Admins can do everything;
  cashiers get an explicit grant list of **screens** and **actions**. Sensitive
  screens (Users, Settings, Backup, Audit) are admin-only and can never be
  granted. Every guard is enforced in the controller/service layer, not merely
  by hiding a button.
- **SQL injection**: every query uses parameter binding — user input is never
  concatenated into SQL.
- **Lockout guards**: you cannot delete/deactivate/demote the last active admin,
  nor delete your own account while logged in.
- **Audit trail**: logins, sales, purchases, voids, user changes, backups, and
  data flushes are recorded append-only with the actor and context.
- **Local-only data**: nothing leaves the machine; the database lives in the
  user's profile folder.

---

## 10. Documents and reports

- **Receipt** (`reports/invoice_pdf.py`) — an **80mm thermal-roll** receipt whose
  height is computed from its content so there is no blank tail wasting paper.
  Every shop field comes from settings (white-label). Shows the payment account,
  and cash change when tendered.
- **Report exporter** (`reports/report_exporter.py`) — one renderer turns any
  report into a styled landscape **PDF** or a computable **Excel** sheet, with
  special multi-section layouts for the Day-Close and Monthly reports.

---

## 11. Building and packaging

- `penguix.spec` tells PyInstaller to bundle the Python code, Qt, `schema.sql`,
  and the logo assets into one windowed `.exe`.
- `build_exe.bat` runs PyInstaller; `installer/build_installer.bat` wraps the
  result with Inno Setup into `Penguix-Setup-<version>.exe`.
- The version lives in `lubripos/__init__.py` and the installer script; it is
  bumped together on each release (current: **0.4.0**).
- On first launch the migrations upgrade any existing database automatically, so
  a shop can install a new version straight over the old one without data loss.

---

## 12. Testing

There are **14 headless test suites** in `tests/` (200+ individual checks) that
exercise the service and reporting layers directly — no GUI required. They cover
the money maths, sales and stock rules, purchases, pricing/markup, reports and
exporters, backup/restore, users, permissions, payment accounts, stock
adjustment, and the data flush. Each runs against a throwaway temporary database,
so they are fast, isolated, and safe to run on every change. This suite is what
made rapid, confident iteration possible.

---

## 13. How it was built — the journey

Penguix grew iteratively from a written specification into a production-grade
app. The foundation came first: the four-layer architecture, the integer-money
discipline, the schema, and the headless test harness. From there each feature
was added as a self-contained slice — service logic + controller + view + tests —
and verified before moving on.

Major milestones along the way included: markup-over-cost pricing; a native
Windows look; fast data-entry aids (save-and-add-another, last-used defaults,
duplicate-barcode warnings); stock adjustment with an audit trail; the audit-log
viewer; a configurable GST/tax report; a one-click data flush for reselling the
software to a new shop; barcode-scanner fixes and an oversell guard; a complete
reports overhaul (the grid Day-Close sheet, monthly by-day-and-by-product,
itemised purchases); guarded user deletion; named payment accounts with
per-account day-close totals; the 80mm thermal receipt; date filters on Expenses
and Purchases; dashboard refinements and a GST on/off switch that hides tax
everywhere when disabled; and finally a full per-user privilege system with
grantable screen and action permissions.

Throughout, a few principles held constant: money stays an integer; history is
snapshotted and never rewritten; business rules and access checks live in the
service/controller layers where tests can reach them; migrations upgrade real
databases safely; and every change is proven by the headless test suite before
it ships.

---

*Document generated for the Penguix (LubriPOS) project — version 0.4.0.*
