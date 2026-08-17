"""Expenses: record shop costs (rent, electricity, salaries, misc...).

Amounts stored as integer minor units. Categories come from a small editable
lookup (expense_categories) but the expense row keeps the category as text so
historical records are stable even if a category is later renamed/removed.
Deletes are hard (expenses are standalone, referenced by nothing) but every
create/update/delete is recorded in the audit log.
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

_EDITABLE = {"expense_date", "category", "amount_minor", "description"}


class ExpenseService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- categories ---------------------------------------------------
    def list_categories(self) -> list[dict]:
        rows = self.db.query(
            "SELECT id, name FROM expense_categories WHERE is_active = 1 "
            "ORDER BY name COLLATE NOCASE"
        )
        return [dict(r) for r in rows]

    def add_category(self, name: str, *, user_id: int | None = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Category name cannot be empty.")
        existing = self.db.query_one(
            "SELECT id FROM expense_categories WHERE name = ? COLLATE NOCASE", (name,)
        )
        if existing:
            return existing["id"]
        cur = self.db.execute("INSERT INTO expense_categories (name) VALUES (?)", (name,))
        self.audit.record(action="CREATE", user_id=user_id,
                          entity_type="expense_category", entity_id=cur.lastrowid,
                          details={"name": name})
        return cur.lastrowid

    # -- reads --------------------------------------------------------
    def list_expenses(
        self,
        *,
        search: str = "",
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses, params = [], []
        if search:
            clauses.append("e.description LIKE ?")
            params.append(f"%{search.strip()}%")
        if category:
            clauses.append("e.category = ?")
            params.append(category)
        if date_from:
            clauses.append("e.expense_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("e.expense_date <= ?")
            params.append(date_to + " 23:59:59")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM expenses e {where}", tuple(params)
        )["n"]
        sum_minor = self.db.query_one(
            f"SELECT COALESCE(SUM(e.amount_minor),0) AS s FROM expenses e {where}",
            tuple(params),
        )["s"]
        rows = self.db.query(
            f"""SELECT e.*, u.username AS created_by_name
                FROM expenses e LEFT JOIN users u ON u.id = e.created_by
                {where} ORDER BY e.expense_date DESC, e.id DESC LIMIT ? OFFSET ?""",
            (*params, int(limit), int(offset)),
        )
        return {"rows": [dict(r) for r in rows], "total": total, "sum_minor": sum_minor}

    def get(self, expense_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM expenses WHERE id = ?", (expense_id,))
        if not row:
            raise NotFoundError(f"Expense {expense_id} not found")
        return dict(row)

    # -- writes -------------------------------------------------------
    def create(self, data: dict[str, Any], *, user_id: int | None = None) -> int:
        clean = self._validate(data, creating=True)
        clean["created_by"] = user_id
        cols = ", ".join(clean)
        ph = ", ".join("?" for _ in clean)
        cur = self.db.execute(
            f"INSERT INTO expenses ({cols}) VALUES ({ph})", tuple(clean.values())
        )
        self.audit.record(action="CREATE", user_id=user_id, entity_type="expense",
                          entity_id=cur.lastrowid,
                          details={"category": clean.get("category"),
                                   "amount_minor": clean.get("amount_minor")})
        log.info("Created expense id=%s amount_minor=%s", cur.lastrowid,
                 clean.get("amount_minor"))
        return cur.lastrowid

    def update(self, expense_id: int, data: dict[str, Any],
               *, user_id: int | None = None) -> None:
        self.get(expense_id)
        clean = self._validate(data, creating=False)
        if not clean:
            return
        set_clause = ", ".join(f"{k} = ?" for k in clean)
        self.db.execute(
            f"UPDATE expenses SET {set_clause} WHERE id = ?",
            (*clean.values(), expense_id),
        )
        self.audit.record(action="UPDATE", user_id=user_id, entity_type="expense",
                          entity_id=expense_id, details={"fields": list(clean)})

    def delete(self, expense_id: int, *, user_id: int | None = None) -> None:
        self.get(expense_id)
        self.db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        self.audit.record(action="DELETE", user_id=user_id, entity_type="expense",
                          entity_id=expense_id)
        log.info("Deleted expense id=%s", expense_id)

    # -- helpers ------------------------------------------------------
    def _validate(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        clean = {k: v for k, v in data.items() if k in _EDITABLE}
        if "category" in clean:
            clean["category"] = (clean["category"] or "").strip()
        if creating and not clean.get("category"):
            raise ValidationError("Expense category is required.")
        if "amount_minor" in clean and int(clean["amount_minor"]) < 0:
            raise ValidationError("Amount cannot be negative.")
        if creating and "amount_minor" not in clean:
            raise ValidationError("Amount is required.")
        return clean
