"""Customers: an optional directory that lets a shop look up a returning
customer's purchase history (e.g. "which engine oil did they buy last time?").

A returning customer is matched on (name, phone) per the owner's choice. Phone
is normalised to digits so "0300-1234567" and "0300 1234567" match. Attaching a
customer to a sale is always optional — walk-in sales keep customer_id NULL.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging_config import get_logger
from ..database.connection import Database
from .audit_service import AuditService

log = get_logger(__name__)

_SORT_COLUMNS = {
    "name": "c.name COLLATE NOCASE",
    "last_purchase": "last_purchase",
    "total_spent": "total_spent",
    "sales_count": "sales_count",
}
_EDITABLE = {"name", "phone", "notes"}


def _norm_phone(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


class CustomerService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit or AuditService(db)

    # -- find or create (used at checkout) ----------------------------
    def find_or_create(self, name: str, phone: str | None = None,
                      *, user_id: int | None = None) -> int:
        """Return the id of the customer matching (name, phone), creating one
        if needed. Requires a non-empty name."""
        name = (name or "").strip()
        phone = _norm_phone(phone)
        if not name:
            raise ValidationError("A customer name is required to save a customer.")
        row = self.db.query_one(
            "SELECT id FROM customers WHERE name = ? COLLATE NOCASE AND phone = ?",
            (name, phone))
        if row:
            return row["id"]
        cur = self.db.execute(
            "INSERT INTO customers (name, phone) VALUES (?, ?)", (name, phone))
        new_id = cur.lastrowid
        self.audit.record(action="CREATE", user_id=user_id, entity_type="customer",
                          entity_id=new_id, details={"name": name})
        log.info("Created customer id=%s name=%r", new_id, name)
        return new_id

    # -- reads --------------------------------------------------------
    def list_customers(self, *, search: str = "", only_active: bool = True,
                       sort_by: str = "name", sort_dir: str = "asc",
                       limit: int = 25, offset: int = 0) -> dict[str, Any]:
        clauses, params = [], []
        if only_active:
            clauses.append("c.is_active = 1")
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(c.name LIKE ? OR c.phone LIKE ?)")
            params += [like, like]
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sort_expr = _SORT_COLUMNS.get(sort_by, "c.name COLLATE NOCASE")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

        agg = ("LEFT JOIN (SELECT customer_id, COUNT(*) AS n, "
               "MAX(sale_date) AS last_date, SUM(grand_total_minor) AS spent "
               "FROM sales WHERE status='completed' AND customer_id IS NOT NULL "
               "GROUP BY customer_id) a ON a.customer_id = c.id")
        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM customers c {where}", tuple(params))["n"]
        rows = self.db.query(
            f"SELECT c.*, COALESCE(a.n,0) AS sales_count, a.last_date AS last_purchase, "
            f"COALESCE(a.spent,0) AS total_spent FROM customers c {agg} {where} "
            f"ORDER BY {sort_expr} {direction}, c.id LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)))
        return {"rows": [dict(r) for r in rows], "total": total}

    def get(self, customer_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
        if not row:
            raise NotFoundError(f"Customer {customer_id} not found")
        return dict(row)

    def search_min(self, term: str, limit: int = 20) -> list[dict]:
        """Lightweight lookup for the POS customer picker (name or phone)."""
        like = f"%{(term or '').strip()}%"
        rows = self.db.query(
            "SELECT id, name, phone FROM customers WHERE is_active = 1 "
            "AND (name LIKE ? OR phone LIKE ?) ORDER BY name COLLATE NOCASE LIMIT ?",
            (like, like, int(limit)))
        return [dict(r) for r in rows]

    def last_products(self, customer_id: int, limit: int = 3) -> list[str]:
        """Most recent distinct product names this customer bought (for a POS
        hint). Empty list if none."""
        rows = self.db.query(
            "SELECT si.product_name AS product, MAX(s.sale_date) AS last_date "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.customer_id = ? AND s.status = 'completed' "
            "GROUP BY si.product_name ORDER BY last_date DESC LIMIT ?",
            (customer_id, int(limit)))
        return [r["product"] for r in rows]

    def purchased_products(self, customer_id: int) -> list[dict]:
        """Distinct products this customer has bought that are STILL active,
        with the current sale price and stock (for the POS reorder dialog).
        Keys match what the POS add-to-cart expects (id, name, sale_price_minor,
        stock_qty)."""
        rows = self.db.query(
            """SELECT p.id AS id, p.name AS name,
                  p.sale_price_minor AS sale_price_minor, p.stock_qty AS stock_qty,
                  SUM(si.qty) AS total_qty, MAX(s.sale_date) AS last_date
               FROM sale_items si
               JOIN sales s ON s.id = si.sale_id
               JOIN products p ON p.id = si.product_id
               WHERE s.customer_id = ? AND s.status = 'completed' AND p.is_active = 1
               GROUP BY p.id ORDER BY last_date DESC""", (customer_id,))
        return [dict(r) for r in rows]

    def history(self, customer_id: int) -> dict[str, Any]:
        """Full history: the products this customer has bought (with qty, how
        many visits, last date, last price) plus the list of their sales."""
        cust = self.get(customer_id)
        # One row per product this customer ever bought: total qty, how many
        # visits it appeared in, and when. The correlated sub-query pulls the
        # price from that customer's MOST RECENT purchase of the product (a plain
        # GROUP BY can't pick "the price from the latest row").
        products = [dict(r) for r in self.db.query(
            """SELECT si.product_name AS product, SUM(si.qty) AS qty,
                  COUNT(DISTINCT s.id) AS visits, MAX(s.sale_date) AS last_date,
                  (SELECT si2.unit_price_minor FROM sale_items si2
                     JOIN sales s2 ON s2.id = si2.sale_id
                     WHERE s2.customer_id = ? AND si2.product_name = si.product_name
                     ORDER BY s2.sale_date DESC LIMIT 1) AS last_price
               FROM sale_items si JOIN sales s ON s.id = si.sale_id
               WHERE s.customer_id = ? AND s.status = 'completed'
               GROUP BY si.product_name ORDER BY last_date DESC""",
            (customer_id, customer_id))]
        sales = [dict(r) for r in self.db.query(
            """SELECT s.id, s.invoice_no AS invoice, substr(s.sale_date,1,16) AS date,
                  s.grand_total_minor AS total,
                  (SELECT COUNT(*) FROM sale_items x WHERE x.sale_id = s.id) AS items
               FROM sales s WHERE s.customer_id = ? AND s.status = 'completed'
               ORDER BY s.sale_date DESC""", (customer_id,))]
        total_spent = sum(x["total"] for x in sales)
        return {"customer": cust, "products": products, "sales": sales,
                "visits": len(sales), "total_spent": total_spent}

    # -- writes -------------------------------------------------------
    def update(self, customer_id: int, data: dict[str, Any],
               *, user_id: int | None = None) -> None:
        self.get(customer_id)
        clean = {k: (v.strip() if isinstance(v, str) else v)
                 for k, v in data.items() if k in _EDITABLE}
        if "phone" in clean:
            clean["phone"] = _norm_phone(clean["phone"])
        if "name" in clean and not clean["name"]:
            raise ValidationError("Customer name cannot be empty.")
        if not clean:
            return
        sets = ", ".join(f"{k} = ?" for k in clean)
        self.db.execute(
            f"UPDATE customers SET {sets}, "
            f"updated_at = strftime('%Y-%m-%d %H:%M:%S','now') WHERE id = ?",
            (*clean.values(), customer_id))
        self.audit.record(action="UPDATE", user_id=user_id, entity_type="customer",
                          entity_id=customer_id, details={"fields": list(clean)})

    def set_active(self, customer_id: int, active: bool,
                   *, user_id: int | None = None) -> None:
        self.db.execute("UPDATE customers SET is_active = ? WHERE id = ?",
                        (1 if active else 0, customer_id))
        self.audit.record(action="DELETE" if not active else "UPDATE",
                          user_id=user_id, entity_type="customer",
                          entity_id=customer_id, details={"is_active": bool(active)})

    def delete(self, customer_id: int, *, user_id: int | None = None) -> None:
        """Permanent delete. Past sales keep their customer_name snapshot; the
        customer_id link is set to NULL (FK ON DELETE SET NULL)."""
        self.get(customer_id)
        self.db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        self.audit.record(action="DELETE", user_id=user_id, entity_type="customer",
                          entity_id=customer_id)
        log.info("Permanently deleted customer id=%s", customer_id)
