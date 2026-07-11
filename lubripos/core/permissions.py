"""Per-user privileges: which SCREENS a user may open and which ACTIONS they
may perform.

Admins implicitly have everything. Only non-admin (cashier) users carry an
explicit grant list, stored as a JSON array in users.permissions. Sensitive
screens (Users, Settings, Backup/Restore, Audit) are admin-only and never
appear here, so they can never be granted to a non-admin.
"""
from __future__ import annotations

import json

# Grantable screens: (permission key == nav key, human label).
SCREEN_PERMISSIONS = [
    ("dashboard", "Dashboard"),
    ("pos", "Sale (POS)"),
    ("sales", "Sales History"),
    ("products", "Products"),
    ("taxonomy", "Categories & Brands"),
    ("suppliers", "Suppliers"),
    ("purchases", "Purchases"),
    ("expenses", "Expenses"),
    ("reports", "Reports"),
]

# Grantable actions (finer control within screens).
ACTION_PERMISSIONS = [
    ("sale.void", "Void / reverse a sale"),
    ("sale.discount", "Give a discount at checkout"),
    ("sale.edit_price", "Change a price on a sale line"),
]

# Admin-only screens: never grantable to a non-admin.
ADMIN_ONLY_SCREENS = ("users", "audit", "backup", "settings")

SCREEN_KEYS = [k for k, _ in SCREEN_PERMISSIONS]
ACTION_KEYS = [k for k, _ in ACTION_PERMISSIONS]
GRANTABLE_KEYS = SCREEN_KEYS + ACTION_KEYS

# Sensible default for a brand-new cashier and for backfilling legacy accounts.
DEFAULT_CASHIER = ["dashboard", "pos", "sales"]


def clean(keys) -> list[str]:
    """Keep only recognised grantable keys, de-duplicated, in canonical order."""
    given = set(keys or [])
    return [k for k in GRANTABLE_KEYS if k in given]


def serialize(keys) -> str:
    return json.dumps(clean(keys))


def parse(raw) -> set[str]:
    """Parse the stored JSON array into a set of valid keys (robust to junk)."""
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    if not isinstance(data, list):
        return set()
    return set(clean(data))
