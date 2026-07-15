"""Company (shop) settings + tax settings — the white-label core.

Everything the invoice and UI need about shop identity comes from here.
No business name is ever hardcoded; the app reads this single row.
"""
from __future__ import annotations

from typing import Any

from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

_COMPANY_FIELDS = {
    "shop_name", "owner_name", "phone", "email", "address", "logo_path",
    "ntn_number", "gst_number", "currency_code", "currency_symbol",
    "currency_minor_units", "invoice_prefix", "invoice_footer",
    "language", "touch_mode",
}
_TAX_FIELDS = {"tax_enabled", "tax_label", "tax_rate_bps", "tax_inclusive"}


class CompanyService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- company ------------------------------------------------------
    def get_company(self) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM company_settings WHERE id = 1")
        return dict(row) if row else {}

    def update_company(self, updates: dict[str, Any], *, user_id: int | None = None) -> None:
        fields = {k: v for k, v in updates.items() if k in _COMPANY_FIELDS}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE company_settings SET {set_clause} WHERE id = 1",
            tuple(fields.values()),
        )
        self.audit.record(action="UPDATE", user_id=user_id, entity_type="company_settings",
                          entity_id=1, details={"fields": list(fields)})
        log.info("Company settings updated: %s", list(fields))

    # -- tax ----------------------------------------------------------
    def get_tax(self) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM tax_settings WHERE id = 1")
        return dict(row) if row else {}

    def update_tax(self, updates: dict[str, Any], *, user_id: int | None = None) -> None:
        fields = {k: v for k, v in updates.items() if k in _TAX_FIELDS}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE tax_settings SET {set_clause} WHERE id = 1",
            tuple(fields.values()),
        )
        self.audit.record(action="UPDATE", user_id=user_id, entity_type="tax_settings",
                          entity_id=1, details={"fields": list(fields)})
        log.info("Tax settings updated: %s", list(fields))
