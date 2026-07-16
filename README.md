# Penguix — Lubricant & Auto Parts Management System

White-label, single-tenant **desktop POS + inventory + accounting** for
lubricant shops, auto-parts stores, and oil & grease distributors.
**One installation = one shop.** The shop's identity (name, address, logo,
currency, tax, language) comes entirely from the `company_settings` table —
nothing is hardcoded, so the same build serves any business.

**Stack:** Python 3.13+ · PySide6 · SQLite (WAL) · ReportLab · OpenPyXL · MVC + service layer
**Platform:** Windows desktop. **Version:** 0.5.9  ·  **Schema version:** 10

---

## Run (development)

```bash
python -m venv .venv
# Windows:        .venv\Scripts\activate
# Linux/macOS:    source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

First launch creates the database, schema, and seed data automatically.

**Default login:** `admin` / `admin123` — you are **forced to set a new password**
on first sign-in.

Data (database, logs, backups) is stored per-user, **outside** the program
folder, so the app works from Program Files and survives reinstalls:

- Windows: `%APPDATA%\Penguix`
- macOS: `~/Library/Application Support/Penguix`
- Linux: `~/.local/share/Penguix`

Override with the `LUBRIPOS_HOME` environment variable (handy for testing).
A legacy `LubriPOS` data folder, if present, is migrated automatically on first run.

---

## Build a Windows installer

```powershell
# 1. ALWAYS activate the venv first (else PyInstaller isn't on PATH)
& .\.venv\Scripts\Activate.ps1

# 2. Build the single-file exe  ->  dist\Penguix.exe
.\build_exe.bat

# 3. Build the installer  ->  installer\output\Penguix-Setup-x.y.z.exe
.\installer\build_installer.bat        # or open the .iss in Inno Setup and press F9
```

`build_exe.bat` now refuses to run if PyInstaller isn't importable and deletes the
old exe first, so a stale build can never masquerade as a success. Requires
PyInstaller (bundled dep) and Inno Setup 6.

---

## Architecture (MVC + service layer)

```
main.py                # entry point: login -> main window loop; installs crash handler
lubripos/
  config.py            # cross-platform paths (%APPDATA%\Penguix)
  app_context.py       # composition root (wires DB + shared services)
  core/                # money (integer minor units), security (PBKDF2), session/roles,
                       # permissions (per-user grants), i18n (Urdu/English), exceptions,
                       # logging, ed25519 (pure-Python signature verify for updates)
  database/            # connection (WAL, FK on), schema.sql, init / migrate / seed
  services/            # ALL business logic + SQL (products, sales, returns, purchases,
                       # payables, customers, reports, backup, update, company, ...)
  controllers/         # mediate views <-> services, enforce roles/permissions, convert money
  views/               # PySide6 screens (no SQL, no business logic)
  ui/                  # theme (QSS), SVG icons, shared widgets, on-screen numeric keypad
  reports/             # PDF invoices + PDF/Excel report exporters
tools/                 # keygen.py (Ed25519 update keys) + release.py (sign the update manifest)
docs/                  # AUTO_UPDATE.md, HOW_PENGUIX_WAS_BUILT.md
```

Rule of thumb: **views never touch the database; services never import Qt.**

---

## Key engineering decisions

- **Money = INTEGER minor units** (paisa/cents). Never float. Formatted only at
  the UI edge via `core/money.py`.
- **Tax = INTEGER basis points** (1700 = 17.00%), single source of truth in
  `tax_settings`; enable/disable and inclusive/exclusive per shop.
- **Passwords:** PBKDF2-HMAC-SHA256, per-user salt, 240k iterations, constant-time verify.
- **No hard deletes** on products/users/suppliers/customers (soft `is_active`); sale,
  purchase and return lines **snapshot** name + price + cost so history never changes
  when a product is later edited.
- **Transactions** wrap multi-step writes (sale + stock decrement, purchase + stock-in,
  return + restock) so a crash can't corrupt stock.
- **Returns are a ledger, net-of-returns:** completed sales stay unchanged; refunds are
  recorded in `sale_returns`/`sale_return_items` and netted out of the day-close and
  profit reports. Stock is added back per returned line.
- **Per-user permissions:** admins have everything; cashiers carry a JSON grant list
  (`users.permissions`) of screens + actions. Sensitive screens (Users, Settings, Backup,
  Audit) are admin-only and can never be granted.
- **Auto-update** is opt-in and **admin-only**, using an **Ed25519-signed manifest** on
  GitHub Releases; the app verifies the signature and the installer's SHA-256 before
  installing. See `docs/AUTO_UPDATE.md`.
- **Backups** use SQLite's online-backup API (a consistent whole-database snapshot —
  every table), with daily auto-backup, manual backup to a **chosen location**, and
  restore (writes a safety backup first).
- **Audit log** is append-only.

---

## Features

- **Products** — CRUD, indexed barcode/name search, inline price + margin editing,
  low-stock highlighting, units (Piece/Bottle/Carton/Litre/Kg).
- **Categories & Brands** — dynamic; dedicated management screen + add-inline.
- **Suppliers + Purchases** — multi-line purchases, atomic auto stock-in, history,
  itemised purchase report, and an optional "amount paid now" (credit purchases).
- **Supplier Payables** — track what the shop owes each supplier, record payments,
  per-supplier ledger. (Kept out of the P&L — buying stock isn't an expense.)
- **POS / Sales** — barcode scan, category-filtered product search, cart, configurable
  GST, transactional stock decrement, named payment accounts (Cash/Bank/EasyPaisa/JazzCash),
  optional customer attach + "reorder from history".
- **Returns** — partial / line-level returns by invoice: pick quantities, refund, restock.
- **Customers** — optional directory keyed on (name, phone); per-customer purchase history
  ("which oil did they buy?") and one-click reorder into the cart.
- **Invoices / receipt** — 80 mm thermal receipt + A4 ReportLab PDF, print, reprint;
  shop logo + configurable footer.
- **Expenses** — categorised tracking with date filters and per-row edit/delete.
- **Reports** — 8 reports (daily day-close, monthly, profit, stock, low stock, purchases,
  expenses, tax), each with PDF + Excel export + print; profit/day-close are net of returns.
- **Dashboard** — today/week/month toggle, sales trend chart, sales/profit/expenses,
  stock value, low-stock + inactive-product alerts.
- **Settings (tabbed, admin-only)** — Shop · Currency & Invoice · Display (language +
  touchscreen) · Tax · Payment Accounts · Updates · Danger Zone (flush).
- **Localization** — English / Urdu toggle (counter screens, LTR); optional on-screen
  numeric keypad for touchscreens.
- **Backup & restore** — whole-database online backup, daily auto-backup, restore,
  choose-save-location, configurable auto-backup folder.
- **Users & roles** — admin CRUD, password reset, active control, per-user privileges.

---

## Tests

19 headless suites run against an isolated temp database (`LUBRIPOS_HOME`), and run
automatically in CI on every push (`.github/workflows/tests.yml`):

```bash
for t in tests/test_*.py; do python "$t"; done
```

`test_foundation · products · purchases · sales · invoice · expenses · reports · backup ·
users · pricing · stock_adjust · payment_accounts · permissions · returns · payables ·
customers · i18n · update · flush`

---

## Roadmap

- **Authenticode code-signing** of the installer (removes the SmartScreen "unknown
  publisher" warning) — separate from the update system, added when distributing widely.
- **Licensing / activation** (offline Ed25519-signed keys, perpetual per major version,
  node-locked) — designed, to be added before commercial distribution.
