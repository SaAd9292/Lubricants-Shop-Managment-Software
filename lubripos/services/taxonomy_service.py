"""Categories and brands management.

Used by the product form (dropdowns + inline add) and the dedicated
Categories & Brands screen. Names are unique (case-insensitive). Items are
referenced by products via SET NULL, so deactivating (soft) is preferred over
deleting; rename is supported and safe.
"""
from __future__ import annotations

from ..core.exceptions import ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

_TABLES = {"categories", "brands"}


class TaxonomyService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- reads --------------------------------------------------------
    def list_categories(self, active_only: bool = True) -> list[dict]:
        return self._list("categories", active_only)

    def list_brands(self, active_only: bool = True) -> list[dict]:
        return self._list("brands", active_only)

    def _list(self, table: str, active_only: bool) -> list[dict]:
        self._guard(table)
        fk = "category_id" if table == "categories" else "brand_id"
        sql = (f"SELECT t.id, t.name, t.is_active, "
               f"(SELECT COUNT(*) FROM products p WHERE p.{fk} = t.id) AS product_count "
               f"FROM {table} t")
        if active_only:
            sql += " WHERE t.is_active = 1"
        sql += " ORDER BY t.name COLLATE NOCASE"
        return [dict(r) for r in self.db.query(sql)]

    # -- writes -------------------------------------------------------
    def add_category(self, name: str, *, user_id: int | None = None) -> int:
        return self._add("categories", name, user_id)

    def add_brand(self, name: str, *, user_id: int | None = None) -> int:
        return self._add("brands", name, user_id)

    def _add(self, table: str, name: str, user_id: int | None) -> int:
        self._guard(table)
        name = (name or "").strip()
        if not name:
            raise ValidationError("Name cannot be empty.")
        existing = self.db.query_one(
            f"SELECT id FROM {table} WHERE name = ? COLLATE NOCASE", (name,)
        )
        if existing:
            return existing["id"]
        cur = self.db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
        new_id = cur.lastrowid
        self.audit.record(action="CREATE", user_id=user_id, entity_type=table,
                          entity_id=new_id, details={"name": name})
        log.info("Added %s '%s' (id=%s)", table[:-1], name, new_id)
        return new_id

    def rename(self, table: str, item_id: int, new_name: str,
               *, user_id: int | None = None) -> None:
        self._guard(table)
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValidationError("Name cannot be empty.")
        clash = self.db.query_one(
            f"SELECT id FROM {table} WHERE name = ? COLLATE NOCASE AND id != ?",
            (new_name, item_id),
        )
        if clash:
            raise ValidationError(f"'{new_name}' already exists.")
        self.db.execute(f"UPDATE {table} SET name = ? WHERE id = ?", (new_name, item_id))
        self.audit.record(action="UPDATE", user_id=user_id, entity_type=table,
                          entity_id=item_id, details={"name": new_name})
        log.info("Renamed %s id=%s -> %r", table[:-1], item_id, new_name)

    def set_active(self, table: str, item_id: int, active: bool,
                   *, user_id: int | None = None) -> None:
        self._guard(table)
        self.db.execute(
            f"UPDATE {table} SET is_active = ? WHERE id = ?",
            (1 if active else 0, item_id),
        )
        self.audit.record(action="UPDATE", user_id=user_id, entity_type=table,
                          entity_id=item_id, details={"is_active": bool(active)})

    def delete(self, table: str, item_id: int, *, user_id: int | None = None) -> None:
        """Permanent delete. Products referencing it are set to NULL (FK ON DELETE SET NULL)."""
        self._guard(table)
        self.db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        self.audit.record(action="DELETE", user_id=user_id, entity_type=table,
                          entity_id=item_id)
        log.info("Deleted %s id=%s (permanent)", table[:-1], item_id)

    @staticmethod
    def _guard(table: str) -> None:
        # Defense-in-depth: table name is interpolated into SQL, so it must
        # come only from this fixed whitelist (never user input).
        if table not in _TABLES:
            raise ValidationError(f"Unknown taxonomy table: {table!r}")
