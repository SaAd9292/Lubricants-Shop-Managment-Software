"""Read-only aggregates for the dashboard.

All money returned in minor units; the view formats it. Queries are written
to use the existing indexes (sale_date, expense_date, is_active).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..database.connection import Database


class DashboardService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _period_start(period: str) -> str:
        """Inclusive start timestamp for 'today' | 'week' (last 7 days) |
        'month' (calendar month to date)."""
        today = date.today()
        if period == "week":
            d = today - timedelta(days=6)
        elif period == "month":
            d = today.replace(day=1)
        else:
            d = today
        return d.isoformat() + " 00:00:00"

    def summary(self, period: str = "today") -> dict[str, Any]:
        start = self._period_start(period)

        sales = self.db.query_one(
            "SELECT COALESCE(SUM(grand_total_minor),0) AS total, COUNT(*) AS n "
            "FROM sales WHERE status='completed' AND sale_date >= ?", (start,),
        )
        profit = self.db.query_one(
            "SELECT COALESCE(SUM((si.unit_price_minor - si.unit_cost_minor) * si.qty),0) AS profit "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND s.sale_date >= ?", (start,),
        )
        expenses = self.db.query_one(
            "SELECT COALESCE(SUM(amount_minor),0) AS total FROM expenses "
            "WHERE expense_date >= ?", (start,),
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
        inactive_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM products WHERE is_active=0"
        )

        return {
            "today_sales_minor": sales["total"],
            "today_sales_count": sales["n"],
            "today_profit_minor": profit["profit"],
            "today_expenses_minor": expenses["total"],
            "stock_value_minor": stock_value["val"],
            "low_stock_count": low_stock["n"],
            "product_count": product_count["n"],
            "inactive_product_count": inactive_count["n"],
            "period": period,
        }

    def sales_series(self, days: int = 7) -> list[dict[str, Any]]:
        """Daily completed-sales totals for the last `days` days (gaps -> 0),
        oldest first, for the dashboard bar chart."""
        today = date.today()
        start = today - timedelta(days=days - 1)
        rows = self.db.query(
            "SELECT substr(sale_date,1,10) AS day, COALESCE(SUM(grand_total_minor),0) AS total "
            "FROM sales WHERE status='completed' AND sale_date >= ? GROUP BY day",
            (start.isoformat() + " 00:00:00",),
        )
        by = {r["day"]: r["total"] for r in rows}
        out = []
        for i in range(days):
            d = start + timedelta(days=i)
            out.append({"date": d.isoformat(), "label": d.strftime("%a"),
                        "total": by.get(d.isoformat(), 0)})
        return out

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
