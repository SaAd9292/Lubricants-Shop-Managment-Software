"""Read-only aggregates for the dashboard.

All money returned in minor units; the view formats it. Queries are written
to use the existing indexes (sale_date, expense_date, is_active).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..database.connection import Database
from .cash_service import CashService


class DashboardService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- date range ---------------------------------------------------
    @staticmethod
    def _as_date(d: str | None, default: date) -> date:
        if d:
            try:
                return date.fromisoformat(d[:10])
            except ValueError:
                pass
        return default

    def _range(self, date_from: str | None, date_to: str | None) -> tuple[date, date]:
        """Inclusive [from, to] as dates, defaulting to today and always ordered
        (from <= to) so a mis-ordered pair never yields an empty window."""
        today = date.today()
        fd = self._as_date(date_from, today)
        td = self._as_date(date_to, fd)
        return (fd, td) if fd <= td else (td, fd)

    def _prev_range(self, fd: date, td: date) -> tuple[date, date]:
        """The equal-length span immediately before [fd, td], for like-for-like
        deltas (e.g. the 7 days before a 7-day range)."""
        n = (td - fd).days + 1
        return fd - timedelta(days=n), fd - timedelta(days=1)

    @staticmethod
    def _bounds(start_d: date, end_d: date) -> tuple[str, str]:
        """Timestamp bounds covering the full inclusive day range."""
        return start_d.isoformat() + " 00:00:00", end_d.isoformat() + " 23:59:59"

    def _totals(self, start: str, end: str) -> dict[str, int]:
        """Sales / gross profit / expenses within the inclusive [start, end]
        timestamp range."""
        scond = "s.sale_date >= ? AND s.sale_date <= ?"
        sp = (start, end)
        sales = self.db.query_one(
            "SELECT COALESCE(SUM(grand_total_minor),0) AS t, COUNT(*) AS n FROM sales s "
            "WHERE s.status='completed' AND " + scond, sp)
        # profit net of per-line discounts (in line_total) and bill discounts
        line_margin = self.db.query_one(
            "SELECT COALESCE(SUM(si.line_total_minor - si.unit_cost_minor*si.qty),0) AS t "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND " + scond, sp)["t"]
        bill_disc = self.db.query_one(
            "SELECT COALESCE(SUM(discount_minor),0) AS d FROM sales s "
            "WHERE s.status='completed' AND " + scond, sp)["d"]
        exp = self.db.query_one(
            "SELECT COALESCE(SUM(amount_minor),0) AS t FROM expenses "
            "WHERE expense_date >= ? AND expense_date <= ?", (start, end))
        return {"sales": sales["t"], "count": sales["n"],
                "profit": line_margin - bill_disc, "expenses": exp["t"]}

    # -- summary ------------------------------------------------------
    def summary(self, date_from: str | None = None,
                date_to: str | None = None) -> dict[str, Any]:
        fd, td = self._range(date_from, date_to)
        start, end = self._bounds(fd, td)
        t = self._totals(start, end)

        stock_value = self.db.query_one(
            "SELECT COALESCE(SUM(stock_qty * purchase_price_minor),0) AS val "
            "FROM products WHERE is_active=1")
        low_stock = self.db.query_one(
            "SELECT COUNT(*) AS n FROM products "
            "WHERE is_active=1 AND min_stock_level > 0 AND stock_qty <= min_stock_level")
        product_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM products WHERE is_active=1")
        inactive_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM products WHERE is_active=0")

        return {
            "today_sales_minor": t["sales"],
            "today_sales_count": t["count"],
            "today_profit_minor": t["profit"],
            "today_expenses_minor": t["expenses"],
            "stock_value_minor": stock_value["val"],
            # Running physical-drawer cash AS OF the end of the range
            # (for a range ending today this is the live balance).
            "cash_in_hand_minor": CashService(self.db).balance_as_of(td.isoformat()),
            "low_stock_count": low_stock["n"],
            "product_count": product_count["n"],
            "inactive_product_count": inactive_count["n"],
            "window_start": fd.isoformat(),
            "window_end": td.isoformat(),
        }

    def deltas(self, date_from: str | None = None,
               date_to: str | None = None) -> dict[str, Any]:
        """Percent change vs the equal-length span immediately before the range.
        A pct of None means the previous span was zero (no basis)."""
        fd, td = self._range(date_from, date_to)
        pfd, ptd = self._prev_range(fd, td)
        cur = self._totals(*self._bounds(fd, td))
        prev = self._totals(*self._bounds(pfd, ptd))

        def pct(c: int, p: int):
            return None if p == 0 else (c - p) / p * 100.0

        return {
            "sales_pct": pct(cur["sales"], prev["sales"]),
            "profit_pct": pct(cur["profit"], prev["profit"]),
            "expenses_pct": pct(cur["expenses"], prev["expenses"]),
            "label": "vs previous period",
        }

    def top_sellers(self, date_from: str | None = None, date_to: str | None = None,
                    limit: int = 5) -> list[dict]:
        """Best-selling products in the range, by units sold (revenue tiebreak)."""
        start, end = self._bounds(*self._range(date_from, date_to))
        rows = self.db.query(
            "SELECT si.product_name AS name, SUM(si.qty) AS qty, "
            "SUM(si.line_total_minor) AS revenue "
            "FROM sale_items si JOIN sales s ON s.id = si.sale_id "
            "WHERE s.status='completed' AND s.sale_date >= ? AND s.sale_date <= ? "
            "GROUP BY si.product_name ORDER BY qty DESC, revenue DESC LIMIT ?",
            (start, end, limit))
        return [dict(r) for r in rows]

    def sales_in_window(self, date_from: str | None = None, date_to: str | None = None,
                        limit: int = 6) -> list[dict]:
        """Most recent completed sales WITHIN the range (so the list matches the
        range being viewed, not just 'latest overall')."""
        start, end = self._bounds(*self._range(date_from, date_to))
        rows = self.db.query(
            "SELECT invoice_no, sale_date, grand_total_minor, cashier_name "
            "FROM sales WHERE status='completed' AND sale_date >= ? AND sale_date <= ? "
            "ORDER BY id DESC LIMIT ?", (start, end, limit))
        return [dict(r) for r in rows]

    def chart_series(self, date_from: str | None = None,
                     date_to: str | None = None) -> list[dict[str, Any]]:
        """Gross-sales bars across the range: one bar per DAY for ranges up to
        ~two months, otherwise one bar per calendar MONTH so a long range stays
        readable."""
        fd, td = self._range(date_from, date_to)
        days = (td - fd).days + 1
        s_ts, e_ts = self._bounds(fd, td)
        if days <= 62:
            rows = self.db.query(
                "SELECT substr(sale_date,1,10) AS k, "
                "COALESCE(SUM(grand_total_minor),0) AS total "
                "FROM sales WHERE status='completed' AND sale_date >= ? AND sale_date <= ? "
                "GROUP BY k", (s_ts, e_ts))
            by = {r["k"]: r["total"] for r in rows}
            fmt = "%a" if days <= 7 else "%d/%m"
            out = []
            for i in range(days):
                d = fd + timedelta(days=i)
                out.append({"date": d.isoformat(), "label": d.strftime(fmt),
                            "total": by.get(d.isoformat(), 0)})
            return out
        # monthly buckets
        rows = self.db.query(
            "SELECT substr(sale_date,1,7) AS k, "
            "COALESCE(SUM(grand_total_minor),0) AS total "
            "FROM sales WHERE status='completed' AND sale_date >= ? AND sale_date <= ? "
            "GROUP BY k", (s_ts, e_ts))
        by = {r["k"]: r["total"] for r in rows}
        out = []
        y, m = fd.year, fd.month
        while (y, m) <= (td.year, td.month):
            key = f"{y:04d}-{m:02d}"
            out.append({"date": key + "-01", "label": date(y, m, 1).strftime("%b %y"),
                        "total": by.get(key, 0)})
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return out

    def last_cash_count(self) -> dict | None:
        """The most recent end-of-day drawer count (actual vs expected), for the
        dashboard's Actual-vs-Cash-in-Hand display."""
        return CashService(self.db).last_count()

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
