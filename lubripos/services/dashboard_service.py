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
        # Profit is net of BOTH discounts: line_total_minor already has the
        # per-line discount taken off; the whole-bill discount is subtracted once
        # per sale from the sales header.
        line_margin = self.db.query_one(
            "SELECT COALESCE(SUM(si.line_total_minor - si.unit_cost_minor*si.qty),0) AS m "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND s.sale_date >= ?", (start,))["m"]
        bill_disc = self.db.query_one(
            "SELECT COALESCE(SUM(discount_minor),0) AS d FROM sales "
            "WHERE status='completed' AND sale_date >= ?", (start,))["d"]
        profit = {"profit": line_margin - bill_disc}
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
            "WHERE is_active=1 AND min_stock_level > 0 AND stock_qty <= min_stock_level"
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

    def _delta_windows(self, period: str) -> tuple[str, str]:
        """(current_start, previous_start) as timestamps. The previous window is
        the equal-length span immediately BEFORE the current one, so we compare
        like-for-like: today vs yesterday, this week vs the week before, and
        month-to-date vs the same number of days in the prior month."""
        today = date.today()
        if period == "week":
            start = today - timedelta(days=6)
            prev_start = start - timedelta(days=7)
        elif period == "month":
            start = today.replace(day=1)
            length = (today - start).days + 1
            prev_start = start - timedelta(days=length)
        else:  # today
            start = today
            prev_start = today - timedelta(days=1)
        return start.isoformat() + " 00:00:00", prev_start.isoformat() + " 00:00:00"

    def _totals(self, start: str, end: str | None) -> dict[str, int]:
        """Sales / gross profit / expenses within [start, end) (end None = open)."""
        scond, sparams = "s.sale_date >= ?", [start]
        econd, eparams = "expense_date >= ?", [start]
        if end is not None:
            scond += " AND s.sale_date < ?"; sparams.append(end)
            econd += " AND expense_date < ?"; eparams.append(end)
        sales = self.db.query_one(
            "SELECT COALESCE(SUM(grand_total_minor),0) AS t FROM sales s "
            "WHERE s.status='completed' AND " + scond, tuple(sparams))
        # profit net of per-line discounts (in line_total) and bill discounts
        line_margin = self.db.query_one(
            "SELECT COALESCE(SUM(si.line_total_minor - si.unit_cost_minor*si.qty),0) AS t "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND " + scond, tuple(sparams))["t"]
        bill_disc = self.db.query_one(
            "SELECT COALESCE(SUM(discount_minor),0) AS d FROM sales s "
            "WHERE s.status='completed' AND " + scond, tuple(sparams))["d"]
        exp = self.db.query_one(
            "SELECT COALESCE(SUM(amount_minor),0) AS t FROM expenses WHERE " + econd,
            tuple(eparams))
        return {"sales": sales["t"], "profit": line_margin - bill_disc,
                "expenses": exp["t"]}

    def deltas(self, period: str = "today") -> dict[str, Any]:
        """Percent change of sales/profit/expenses vs the previous equal window.
        A pct of None means the previous window was zero (no basis)."""
        start, prev_start = self._delta_windows(period)
        cur = self._totals(start, None)
        prev = self._totals(prev_start, start)

        def pct(c: int, p: int):
            return None if p == 0 else (c - p) / p * 100.0

        label = {"today": "vs yesterday", "week": "vs prev 7 days",
                 "month": "vs last month"}.get(period, "vs previous")
        return {
            "sales_pct": pct(cur["sales"], prev["sales"]),
            "profit_pct": pct(cur["profit"], prev["profit"]),
            "expenses_pct": pct(cur["expenses"], prev["expenses"]),
            "label": label,
        }

    def top_sellers(self, period: str = "today", limit: int = 5) -> list[dict]:
        """Best-selling products in the period, by units sold (revenue tiebreak)."""
        start = self._period_start(period)
        rows = self.db.query(
            "SELECT si.product_name AS name, SUM(si.qty) AS qty, "
            "SUM(si.line_total_minor) AS revenue "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND s.sale_date >= ? "
            "GROUP BY si.product_name ORDER BY qty DESC, revenue DESC LIMIT ?",
            (start, limit))
        return [dict(r) for r in rows]

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

    def negative_stock_count(self) -> int:
        return self.db.query_one(
            "SELECT COUNT(*) AS n FROM products WHERE is_active=1 AND stock_qty < 0"
        )["n"]

    def negative_stock(self, limit: int = 8) -> list[dict]:
        """Active products currently at negative stock (sold from the warehouse
        before their purchase was booked), most negative first."""
        rows = self.db.query(
            "SELECT name, stock_qty FROM products "
            "WHERE is_active=1 AND stock_qty < 0 "
            "ORDER BY stock_qty ASC, name COLLATE NOCASE LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def recent_low_stock(self, limit: int = 6) -> list[dict]:
        rows = self.db.query(
            "SELECT name, stock_qty, min_stock_level FROM products "
            "WHERE is_active=1 AND min_stock_level > 0 AND stock_qty <= min_stock_level "
            "ORDER BY (min_stock_level - stock_qty) DESC, name COLLATE NOCASE LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
