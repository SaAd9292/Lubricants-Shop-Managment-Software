"""Suppliers: CRUD with search, sort, pagination, and soft delete.

Suppliers are referenced by purchases, so deletion is soft (is_active = 0)
to preserve purchase history. The supplier FK on purchases is ON DELETE SET
NULL as an extra safety net.
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

_SORT_COLUMNS = {
    "name": "name",
    "phone": "phone",
    "created_at": "created_at",
}
_EDITABLE = {"name", "phone", "address", "notes"}


class SupplierService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- reads --------------------------------------------------------
    def list_suppliers(
        self,
        *,
        search: str = "",
        only_active: bool = True,
        sort_by: str = "name",
        sort_dir: str = "asc",
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses, params = [], []
        if only_active:
            clauses.append("is_active = 1")
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(name LIKE ? OR phone LIKE ? OR address LIKE ?)")
            params += [like, like, like]
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sort_expr = _SORT_COLUMNS.get(sort_by, "name")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM suppliers {where}", tuple(params)
        )["n"]
        rows = self.db.query(
            f"SELECT s.*, (SELECT COUNT(*) FROM purchases p WHERE p.supplier_id = s.id) "
            f"AS purchase_count FROM suppliers s {where} "
            f"ORDER BY {sort_expr} {direction}, s.id LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        )
        return {"rows": [dict(r) for r in rows], "total": total}

    def get(self, supplier_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        if not row:
            raise NotFoundError(f"Supplier {supplier_id} not found")
        return dict(row)

    def list_active_min(self) -> list[dict]:
        """Lightweight list for dropdowns (id + name)."""
        rows = self.db.query(
            "SELECT id, name FROM suppliers WHERE is_active = 1 ORDER BY name COLLATE NOCASE"
        )
        return [dict(r) for r in rows]

    # -- writes -------------------------------------------------------
    def create(self, data: dict[str, Any], *, user_id: int | None = None) -> int:
        clean = self._validate(data, creating=True)
        cols = ", ".join(clean)
        ph = ", ".join("?" for _ in clean)
        cur = self.db.execute(
            f"INSERT INTO suppliers ({cols}) VALUES ({ph})", tuple(clean.values())
        )
        new_id = cur.lastrowid
        self.audit.record(action="CREATE", user_id=user_id, entity_type="supplier",
                          entity_id=new_id, details={"name": clean.get("name")})
        log.info("Created supplier id=%s name=%r", new_id, clean.get("name"))
        return new_id

    def update(self, supplier_id: int, data: dict[str, Any],
               *, user_id: int | None = None) -> None:
        self.get(supplier_id)
        clean = self._validate(data, creating=False)
        if not clean:
            return
        set_clause = ", ".join(f"{k} = ?" for k in clean)
        self.db.execute(
            f"UPDATE suppliers SET {set_clause} WHERE id = ?",
            (*clean.values(), supplier_id),
        )
        self.audit.record(action="UPDATE", user_id=user_id, entity_type="supplier",
                          entity_id=supplier_id, details={"fields": list(clean)})
        log.info("Updated supplier id=%s", supplier_id)

    def set_active(self, supplier_id: int, active: bool,
                   *, user_id: int | None = None) -> None:
        self.db.execute(
            "UPDATE suppliers SET is_active = ? WHERE id = ?",
            (1 if active else 0, supplier_id),
        )
        self.audit.record(action="DELETE" if not active else "UPDATE",
                          user_id=user_id, entity_type="supplier",
                          entity_id=supplier_id, details={"is_active": bool(active)})

    def delete(self, supplier_id: int, *, user_id: int | None = None) -> None:
        """Permanent delete. Past purchases keep their rows; supplier link is
        set to NULL (FK ON DELETE SET NULL), so history is retained but unnamed."""
        self.get(supplier_id)
        self.db.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        self.audit.record(action="DELETE", user_id=user_id, entity_type="supplier",
                          entity_id=supplier_id)
        log.info("Permanently deleted supplier id=%s", supplier_id)

    # -- helpers ------------------------------------------------------
    def _validate(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        clean = {k: (v.strip() if isinstance(v, str) else v)
                 for k, v in data.items() if k in _EDITABLE}
        if creating and not (clean.get("name") or "").strip():
            raise ValidationError("Supplier name is required.")
        if "name" in clean and not clean["name"]:
            raise ValidationError("Supplier name cannot be empty.")
        return clean
