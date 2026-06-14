"""Read-only aggregates for the dashboard.

All money returned in minor units; the view formats it. Queries are written
to use the existing indexes (sale_date, expense_date, is_active).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..database.connection import Database


class DashboardService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def summary(self) -> dict[str, Any]:
        today = date.today().isoformat()
        like_today = f"{today}%"

        sales = self.db.query_one(
            "SELECT COALESCE(SUM(grand_total_minor),0) AS total, COUNT(*) AS n "
            "FROM sales WHERE status='completed' AND sale_date LIKE ?",
            (like_today,),
        )
        profit = self.db.query_one(
            "SELECT COALESCE(SUM((si.unit_price_minor - si.unit_cost_minor) * si.qty),0) AS profit "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND s.sale_date LIKE ?",
            (like_today,),
        )
        expenses = self.db.query_one(
            "SELECT COALESCE(SUM(amount_minor),0) AS total FROM expenses "
            "WHERE expense_date LIKE ?",
            (like_today,),
        )
        stock_value = self.db.query_one(
            "SELECT COALESCE(SUM(stock_qty * purchase_price_minor),0) AS val "
            "FROM products WHERE is_active=1"
        )
        low_stock = self.db.query_one(
            "SELECT COUNT(*) AS n FROM products "
            "WHERE is_active=1 AND stock_qty <= min_stock_level"
        )
        product_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM products WHERE is_active=1"
        )

        return {
            "today_sales_minor": sales["total"],
            "today_sales_count": sales["n"],
            "today_profit_minor": profit["profit"],
            "today_expenses_minor": expenses["total"],
            "stock_value_minor": stock_value["val"],
            "low_stock_count": low_stock["n"],
            "product_count": product_count["n"],
        }

    def recent_sales(self, limit: int = 6) -> list[dict]:
        rows = self.db.query(
            "SELECT invoice_no, sale_date, grand_total_minor, cashier_name "
            "FROM sales WHERE status='completed' ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def recent_low_stock(self, limit: int = 6) -> list[dict]:
        rows = self.db.query(
            "SELECT name, stock_qty, min_stock_level FROM products "
            "WHERE is_active=1 AND stock_qty <= min_stock_level "
            "ORDER BY (min_stock_level - stock_qty) DESC, name COLLATE NOCASE LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
