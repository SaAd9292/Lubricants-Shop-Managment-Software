"""Reporting engine: 8 reports, one uniform output shape.

Every method returns a dict:
  {key, title, subtitle, columns:[{key,label,align,money}], rows:[{...}], summary:[...]}
Money values are INTEGER minor units; the exporter/preview format them.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from ..database.connection import Database


def _col(key, label, align="left", money=False):
    return {"key": key, "label": label, "align": align, "money": money}


class ReportService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- 1. Daily Sales Report (day-close grid) --------------------
    def daily_sales(self, day: str) -> dict[str, Any]:
        """End-of-day close sheet. Returns a multi-section (layout='day_close')
        report: every sale LINE (each sale on its own row), the day's expenses,
        and the money received split BY PAYMENT METHOD (cash / bank / EasyPaisa
        / JazzCash), plus an overall summary. Rendered as a grid on screen and
        as a one-page sheet in PDF/Excel."""
        like = f"{day}%"

        # -- section 1: every sale LINE (each sale on its own row, even when
        #    the same product is sold across several invoices) --
        line_rows = [dict(r) for r in self.db.query(
            """SELECT s.invoice_no AS invoice, substr(s.sale_date,12,5) AS time,
                  si.product_name AS product, si.qty AS qty,
                  si.unit_price_minor AS price, si.line_total_minor AS amount
               FROM sale_items si JOIN sales s ON s.id = si.sale_id
               WHERE s.status='completed' AND s.sale_date LIKE ?
               ORDER BY s.id, si.id""", (like,))]
        items_subtotal = sum(r["amount"] for r in line_rows)

        # -- section 2: expenses for the day --
        exp_rows = [dict(r) for r in self.db.query(
            """SELECT category, COALESCE(description, '') AS description,
                  amount_minor AS amount
               FROM expenses WHERE expense_date LIKE ?
               ORDER BY amount_minor DESC""", (like,))]
        expense_total = sum(r["amount"] for r in exp_rows)

        # -- section 3: money received. pay_rows aggregates by METHOD (for the
        #    cards); pay_detail_rows breaks it down by the named account. --
        pay_rows = [dict(r) for r in self.db.query(
            """SELECT payment_method AS method, COUNT(*) AS sales,
                  SUM(grand_total_minor) AS amount
               FROM sales WHERE status='completed' AND sale_date LIKE ?
               GROUP BY payment_method ORDER BY amount DESC""", (like,))]
        pay_detail_rows = []
        for r in self.db.query(
            """SELECT payment_method AS method,
                  COALESCE(payment_account_name, '') AS account,
                  COUNT(*) AS sales, SUM(grand_total_minor) AS amount
               FROM sales WHERE status='completed' AND sale_date LIKE ?
               GROUP BY payment_method, payment_account_name
               ORDER BY amount DESC""", (like,)):
            r = dict(r)
            label = f"{r['method']} - {r['account']}" if r["account"] else r["method"]
            pay_detail_rows.append(
                {"method": label, "sales": r["sales"], "amount": r["amount"]})

        # header-level aggregates (grand totals include tax, net of discount)
        agg = self.db.query_one(
            """SELECT COUNT(*) n, COALESCE(SUM(subtotal_minor),0) sub,
                  COALESCE(SUM(discount_minor),0) disc, COALESCE(SUM(tax_minor),0) tax,
                  COALESCE(SUM(grand_total_minor),0) total
               FROM sales WHERE status='completed' AND sale_date LIKE ?""", (like,))
        gross = agg["total"]
        net = gross - expense_total

        # per-method map so the UI can show a card per channel even at zero
        by_method = {r["method"]: r["amount"] for r in pay_rows}

        return {
            "key": "daily_sales", "title": "Daily Sales Report (Day Close)",
            "subtitle": day, "layout": "day_close",
            # generic fallback (sales-by-product) so any single-table consumer
            # still works; the day_close renderer/exporter use `sections`.
            "columns": [
                _col("invoice", "Invoice"), _col("time", "Time"),
                _col("product", "Product"), _col("qty", "Qty", "right"),
                _col("price", "Price", "right", True),
                _col("amount", "Amount", "right", True),
            ],
            "rows": line_rows,
            "sections": [
                {"name": "Sales",
                 "columns": [_col("invoice", "Invoice"), _col("time", "Time"),
                             _col("product", "Product"), _col("qty", "Qty", "right"),
                             _col("price", "Price", "right", True),
                             _col("amount", "Amount", "right", True)],
                 "rows": line_rows,
                 "total_label": "Items subtotal", "total": items_subtotal},
                {"name": "Expenses",
                 "columns": [_col("category", "Category"), _col("description", "Description"),
                             _col("amount", "Amount", "right", True)],
                 "rows": exp_rows,
                 "total_label": "Total expenses", "total": expense_total},
                {"name": "Money received",
                 "columns": [_col("method", "Account"), _col("sales", "Sales", "right"),
                             _col("amount", "Amount", "right", True)],
                 "rows": pay_detail_rows,
                 "total_label": "Total received", "total": gross},
            ],
            "payments": by_method,
            "summary": [
                {"label": "Invoices", "value": agg["n"], "money": False},
                {"label": "Gross sales", "value": gross, "money": True},
                {"label": "Discounts", "value": agg["disc"], "money": True},
                {"label": "Tax collected", "value": agg["tax"], "money": True},
                {"label": "Expenses", "value": expense_total, "money": True},
                {"label": "Net (sales - expenses)", "value": net, "money": True},
            ],
        }

    # ---- 2. Monthly Sales Report (by day + by product) -------------
    def monthly_sales(self, year: int, month: int) -> dict[str, Any]:
        """Multi-section (layout='sections'): a per-DAY summary plus a per-
        PRODUCT breakdown for the month, sharing one overall summary."""
        like = f"{year:04d}-{month:02d}%"
        day_rows = [dict(r) for r in self.db.query(
            """SELECT substr(sale_date,1,10) AS day, COUNT(*) AS sales,
                  SUM(subtotal_minor) sub, SUM(discount_minor) disc,
                  SUM(tax_minor) tax, SUM(grand_total_minor) total
               FROM sales WHERE status='completed' AND sale_date LIKE ?
               GROUP BY day ORDER BY day""", (like,))]
        prod_rows = [dict(r) for r in self.db.query(
            """SELECT si.product_name AS product, SUM(si.qty) AS qty,
                  SUM(si.line_total_minor) AS revenue
               FROM sale_items si JOIN sales s ON s.id = si.sale_id
               WHERE s.status='completed' AND s.sale_date LIKE ?
               GROUP BY si.product_name ORDER BY revenue DESC""", (like,))]
        items_subtotal = sum(r["revenue"] for r in prod_rows)
        agg = self.db.query_one(
            """SELECT COUNT(*) n, COALESCE(SUM(subtotal_minor),0) sub,
                  COALESCE(SUM(discount_minor),0) disc, COALESCE(SUM(tax_minor),0) tax,
                  COALESCE(SUM(grand_total_minor),0) total
               FROM sales WHERE status='completed' AND sale_date LIKE ?""", (like,))
        label = f"{calendar.month_name[month]} {year}"
        return {
            "key": "monthly_sales", "title": "Monthly Sales Report",
            "subtitle": label, "layout": "sections",
            # generic fallback = the per-day table
            "columns": [
                _col("day", "Date"), _col("sales", "Sales", "right"),
                _col("sub", "Subtotal", "right", True), _col("disc", "Discount", "right", True),
                _col("tax", "Tax", "right", True), _col("total", "Total", "right", True),
            ],
            "rows": day_rows,
            "sections": [
                {"name": "By day",
                 "columns": [_col("day", "Date"), _col("sales", "Sales", "right"),
                             _col("sub", "Subtotal", "right", True),
                             _col("disc", "Discount", "right", True),
                             _col("tax", "Tax", "right", True),
                             _col("total", "Total", "right", True)],
                 "rows": day_rows,
                 "total_label": "Month total", "total": agg["total"]},
                {"name": "By product",
                 "columns": [_col("product", "Product"), _col("qty", "Qty Sold", "right"),
                             _col("revenue", "Revenue", "right", True)],
                 "rows": prod_rows,
                 "total_label": "Items subtotal", "total": items_subtotal},
            ],
            "summary": [
                {"label": "Number of sales", "value": agg["n"], "money": False},
                {"label": "Subtotal", "value": agg["sub"], "money": True},
                {"label": "Discounts", "value": agg["disc"], "money": True},
                {"label": "Tax", "value": agg["tax"], "money": True},
                {"label": "Grand Total", "value": agg["total"], "money": True},
            ],
        }

    # ---- 3. Profit Report ------------------------------------------
    def profit(self, date_from: str, date_to: str) -> dict[str, Any]:
        # hi appends 23:59:59 so the BETWEEN range includes the whole end day
        # (dates without a time would otherwise stop at 00:00:00 of date_to).
        lo, hi = date_from, date_to + " 23:59:59"
        # Profit uses the cost SNAPSHOTTED on each sale line (si.unit_cost_minor),
        # not the product's current cost — so historical profit never shifts when
        # a product is repriced later. Gross profit = revenue - COGS per product.
        rows = self.db.query(
            """SELECT si.product_name,
                  SUM(si.qty) qty,
                  SUM(si.line_total_minor) revenue,
                  SUM(si.unit_cost_minor*si.qty) cost,
                  SUM(si.line_total_minor - si.unit_cost_minor*si.qty) profit
               FROM sale_items si JOIN sales s ON s.id=si.sale_id
               WHERE s.status='completed' AND s.sale_date BETWEEN ? AND ?
               GROUP BY si.product_name ORDER BY profit DESC""", (lo, hi))
        data = [dict(r) for r in rows]
        totals = self.db.query_one(
            """SELECT COALESCE(SUM(si.line_total_minor),0) revenue,
                  COALESCE(SUM(si.unit_cost_minor*si.qty),0) cost
               FROM sale_items si JOIN sales s ON s.id=si.sale_id
               WHERE s.status='completed' AND s.sale_date BETWEEN ? AND ?""", (lo, hi))
        sales_agg = self.db.query_one(
            """SELECT COALESCE(SUM(discount_minor),0) disc, COALESCE(SUM(tax_minor),0) tax
               FROM sales WHERE status='completed' AND sale_date BETWEEN ? AND ?""", (lo, hi))
        # Discounts and tax live on the SALES header, not the line items, so they
        # are summed separately. Net profit subtracts whole-sale discounts from
        # gross; tax is pass-through (collected for the govt, not income) so it is
        # reported but NOT subtracted from profit.
        revenue = totals["revenue"]
        cost = totals["cost"]
        gross = revenue - cost
        discounts = sales_agg["disc"]
        net = gross - discounts
        margin = (net / revenue * 100) if revenue else 0
        return {
            "key": "profit", "title": "Profit Report", "subtitle": f"{date_from} to {date_to}",
            "columns": [
                _col("product_name", "Product"), _col("qty", "Qty Sold", "right"),
                _col("revenue", "Revenue", "right", True), _col("cost", "Cost", "right", True),
                _col("profit", "Gross Profit", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Revenue (item totals)", "value": revenue, "money": True},
                {"label": "Cost of goods sold", "value": cost, "money": True},
                {"label": "Gross profit", "value": gross, "money": True},
                {"label": "Discounts given", "value": discounts, "money": True},
                {"label": "Net profit", "value": net, "money": True},
                {"label": "Tax collected (pass-through)", "value": sales_agg["tax"], "money": True},
                {"label": "Net margin %", "value": f"{margin:.1f}%", "money": False},
            ],
        }

    # ---- 4. Stock Report (filterable by brand / product) -----------
    def stock(self, brand_id: int | None = None,
              product_id: int | None = None) -> dict[str, Any]:
        # Build the WHERE incrementally so the optional brand/product filters are
        # applied only when supplied. Always starts from active products; the same
        # clause list + params is reused for both the rows and the summary query.
        clauses, params = ["p.is_active=1"], []
        if brand_id:
            clauses.append("p.brand_id = ?")
            params.append(brand_id)
        if product_id:
            clauses.append("p.id = ?")
            params.append(product_id)
        where = "WHERE " + " AND ".join(clauses)
        rows = self.db.query(
            f"""SELECT p.name, b.name AS brand, c.name AS category, p.stock_qty,
                  p.purchase_price_minor, p.sale_price_minor,
                  (p.stock_qty*p.purchase_price_minor) AS value
               FROM products p
               LEFT JOIN brands b ON b.id=p.brand_id
               LEFT JOIN categories c ON c.id=p.category_id
               {where} ORDER BY p.name COLLATE NOCASE""", tuple(params))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            f"SELECT COUNT(*) n, COALESCE(SUM(p.stock_qty*p.purchase_price_minor),0) val "
            f"FROM products p {where}", tuple(params))
        return {
            "key": "stock", "title": "Stock Report", "subtitle": date.today().isoformat(),
            "columns": [
                _col("name", "Product"), _col("brand", "Brand"), _col("category", "Category"),
                _col("stock_qty", "Stock", "right"),
                _col("purchase_price_minor", "Unit Cost", "right", True),
                _col("value", "Stock Value", "right", True),
                _col("sale_price_minor", "Sale Price", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Active products", "value": agg["n"], "money": False},
                {"label": "Total stock value (at cost)", "value": agg["val"], "money": True},
            ],
        }

    # ---- 5. Low Stock Report ---------------------------------------
    def low_stock(self) -> dict[str, Any]:
        rows = self.db.query(
            """SELECT p.name, b.name AS brand, p.stock_qty, p.min_stock_level,
                  (p.min_stock_level - p.stock_qty) AS shortfall
               FROM products p LEFT JOIN brands b ON b.id=p.brand_id
               WHERE p.is_active=1 AND p.stock_qty <= p.min_stock_level
               ORDER BY shortfall DESC, p.name""")
        data = [dict(r) for r in rows]
        return {
            "key": "low_stock", "title": "Low Stock Report", "subtitle": date.today().isoformat(),
            "columns": [
                _col("name", "Product"), _col("brand", "Brand"),
                _col("stock_qty", "In Stock", "right"),
                _col("min_stock_level", "Min Level", "right"),
                _col("shortfall", "Shortfall", "right"),
            ],
            "rows": data,
            "summary": [{"label": "Products at/below minimum", "value": len(data), "money": False}],
        }

    # ---- 6. Purchase Report (itemized) -----------------------------
    def purchases(self, date_from: str, date_to: str) -> dict[str, Any]:
        # One row per purchased line item so the report records WHAT was bought
        # and AT WHAT price, not just a per-purchase total. Product name is
        # joined from products (COALESCE guards a removed product).
        lo, hi = date_from, date_to + " 23:59:59"
        rows = self.db.query(
            """SELECT substr(p.purchase_date,1,10) AS date,
                  COALESCE(s.name, '—') AS supplier,
                  COALESCE(pr.name, '(removed product)') AS product,
                  pi.qty AS qty,
                  pi.unit_cost_minor AS unit_cost,
                  pi.line_total_minor AS line_total
               FROM purchase_items pi
               JOIN purchases p ON p.id = pi.purchase_id
               LEFT JOIN suppliers s ON s.id = p.supplier_id
               LEFT JOIN products pr ON pr.id = pi.product_id
               WHERE p.purchase_date BETWEEN ? AND ?
               ORDER BY p.purchase_date DESC, p.id DESC, pi.id""",
            (lo, hi))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            """SELECT COUNT(*) n, COALESCE(SUM(pi.qty),0) qty,
                  COALESCE(SUM(pi.line_total_minor),0) total
               FROM purchase_items pi JOIN purchases p ON p.id = pi.purchase_id
               WHERE p.purchase_date BETWEEN ? AND ?""", (lo, hi))
        return {
            "key": "purchases", "title": "Purchase Report", "subtitle": f"{date_from} to {date_to}",
            "columns": [
                _col("date", "Date"), _col("supplier", "Supplier"),
                _col("product", "Product"), _col("qty", "Qty", "right"),
                _col("unit_cost", "Unit Cost", "right", True),
                _col("line_total", "Line Total", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Line items", "value": agg["n"], "money": False},
                {"label": "Total qty purchased", "value": agg["qty"], "money": False},
                {"label": "Total purchased", "value": agg["total"], "money": True},
            ],
        }

    # ---- 7. Expense Report -----------------------------------------
    def expenses(self, date_from: str, date_to: str) -> dict[str, Any]:
        lo, hi = date_from, date_to + " 23:59:59"
        rows = self.db.query(
            """SELECT category, COUNT(*) AS count, SUM(amount_minor) AS amount
               FROM expenses WHERE expense_date BETWEEN ? AND ?
               GROUP BY category ORDER BY amount DESC""", (lo, hi))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            "SELECT COUNT(*) n, COALESCE(SUM(amount_minor),0) total FROM expenses "
            "WHERE expense_date BETWEEN ? AND ?", (lo, hi))
        return {
            "key": "expenses", "title": "Expense Report", "subtitle": f"{date_from} to {date_to}",
            "columns": [
                _col("category", "Category"), _col("count", "Entries", "right"),
                _col("amount", "Amount", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Expense entries", "value": agg["n"], "money": False},
                {"label": "Total expenses", "value": agg["total"], "money": True},
            ],
        }

    # ---- 8. Tax / GST Report ---------------------------------------
    def tax(self, date_from: str, date_to: str) -> dict[str, Any]:
        lo, hi = date_from, date_to + " 23:59:59"
        # Title/columns reflect the shop's configured tax label (e.g. "GST").
        cfg = self.db.query_one(
            "SELECT tax_label, tax_rate_bps FROM tax_settings WHERE id = 1")
        label = (cfg["tax_label"] if cfg and cfg["tax_label"] else "Tax")
        rate_txt = f"{(cfg['tax_rate_bps'] / 100.0) if cfg else 0:g}%"
        rows = self.db.query(
            """SELECT substr(sale_date,1,10) AS day, COUNT(*) AS sales,
                  SUM(subtotal_minor - discount_minor) AS taxable, SUM(tax_minor) AS tax
               FROM sales WHERE status='completed' AND sale_date BETWEEN ? AND ?
               GROUP BY day ORDER BY day""", (lo, hi))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            """SELECT COALESCE(SUM(subtotal_minor - discount_minor),0) taxable,
                  COALESCE(SUM(tax_minor),0) tax
               FROM sales WHERE status='completed' AND sale_date BETWEEN ? AND ?""", (lo, hi))
        return {
            "key": "tax", "title": f"{label} Report",
            "subtitle": f"{date_from} to {date_to}    \u2022    {label} @ {rate_txt}",
            "columns": [
                _col("day", "Date"), _col("sales", "Sales", "right"),
                _col("taxable", "Taxable Amount", "right", True),
                _col("tax", f"{label} Collected", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Taxable amount", "value": agg["taxable"], "money": True},
                {"label": "Total tax collected", "value": agg["tax"], "money": True},
                {"label": f"{label} rate", "value": rate_txt, "money": False},
            ],
        }
