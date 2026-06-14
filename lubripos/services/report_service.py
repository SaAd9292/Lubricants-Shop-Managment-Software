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

    # ---- 1. Daily Sales Report -------------------------------------
    def daily_sales(self, day: str) -> dict[str, Any]:
        like = f"{day}%"
        rows = self.db.query(
            """SELECT s.invoice_no, substr(s.sale_date,12,5) AS time, s.cashier_name,
                  (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id=s.id) AS items,
                  s.subtotal_minor, s.discount_minor, s.tax_minor, s.grand_total_minor
               FROM sales s WHERE s.status='completed' AND s.sale_date LIKE ?
               ORDER BY s.id""", (like,))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            """SELECT COUNT(*) n, COALESCE(SUM(subtotal_minor),0) sub,
                  COALESCE(SUM(discount_minor),0) disc, COALESCE(SUM(tax_minor),0) tax,
                  COALESCE(SUM(grand_total_minor),0) total
               FROM sales WHERE status='completed' AND sale_date LIKE ?""", (like,))
        return {
            "key": "daily_sales", "title": "Daily Sales Report", "subtitle": day,
            "columns": [
                _col("invoice_no", "Invoice"), _col("time", "Time"),
                _col("cashier_name", "Cashier"), _col("items", "Items", "right"),
                _col("subtotal_minor", "Subtotal", "right", True),
                _col("discount_minor", "Discount", "right", True),
                _col("tax_minor", "Tax", "right", True),
                _col("grand_total_minor", "Total", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Number of sales", "value": agg["n"], "money": False},
                {"label": "Subtotal", "value": agg["sub"], "money": True},
                {"label": "Discounts", "value": agg["disc"], "money": True},
                {"label": "Tax", "value": agg["tax"], "money": True},
                {"label": "Grand Total", "value": agg["total"], "money": True},
            ],
        }

    # ---- 2. Monthly Sales Report -----------------------------------
    def monthly_sales(self, year: int, month: int) -> dict[str, Any]:
        like = f"{year:04d}-{month:02d}%"
        rows = self.db.query(
            """SELECT substr(sale_date,1,10) AS day, COUNT(*) AS sales,
                  SUM(subtotal_minor) sub, SUM(discount_minor) disc,
                  SUM(tax_minor) tax, SUM(grand_total_minor) total
               FROM sales WHERE status='completed' AND sale_date LIKE ?
               GROUP BY day ORDER BY day""", (like,))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            """SELECT COUNT(*) n, COALESCE(SUM(subtotal_minor),0) sub,
                  COALESCE(SUM(discount_minor),0) disc, COALESCE(SUM(tax_minor),0) tax,
                  COALESCE(SUM(grand_total_minor),0) total
               FROM sales WHERE status='completed' AND sale_date LIKE ?""", (like,))
        label = f"{calendar.month_name[month]} {year}"
        return {
            "key": "monthly_sales", "title": "Monthly Sales Report", "subtitle": label,
            "columns": [
                _col("day", "Date"), _col("sales", "Sales", "right"),
                _col("sub", "Subtotal", "right", True), _col("disc", "Discount", "right", True),
                _col("tax", "Tax", "right", True), _col("total", "Total", "right", True),
            ],
            "rows": data,
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

    # ---- 6. Purchase Report ----------------------------------------
    def purchases(self, date_from: str, date_to: str) -> dict[str, Any]:
        lo, hi = date_from, date_to + " 23:59:59"
        rows = self.db.query(
            """SELECT substr(p.purchase_date,1,10) AS date, s.name AS supplier,
                  (SELECT COUNT(*) FROM purchase_items pi WHERE pi.purchase_id=p.id) AS lines,
                  (SELECT COALESCE(SUM(qty),0) FROM purchase_items pi WHERE pi.purchase_id=p.id) AS qty,
                  p.total_minor
               FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id
               WHERE p.purchase_date BETWEEN ? AND ? ORDER BY p.purchase_date DESC, p.id DESC""",
            (lo, hi))
        data = [dict(r) for r in rows]
        agg = self.db.query_one(
            "SELECT COUNT(*) n, COALESCE(SUM(total_minor),0) total FROM purchases "
            "WHERE purchase_date BETWEEN ? AND ?", (lo, hi))
        return {
            "key": "purchases", "title": "Purchase Report", "subtitle": f"{date_from} to {date_to}",
            "columns": [
                _col("date", "Date"), _col("supplier", "Supplier"),
                _col("lines", "Lines", "right"), _col("qty", "Total Qty", "right"),
                _col("total_minor", "Amount", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Purchases", "value": agg["n"], "money": False},
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

    # ---- 8. Tax Report ---------------------------------------------
    def tax(self, date_from: str, date_to: str) -> dict[str, Any]:
        lo, hi = date_from, date_to + " 23:59:59"
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
            "key": "tax", "title": "Tax Report", "subtitle": f"{date_from} to {date_to}",
            "columns": [
                _col("day", "Date"), _col("sales", "Sales", "right"),
                _col("taxable", "Taxable Amount", "right", True),
                _col("tax", "Tax Collected", "right", True),
            ],
            "rows": data,
            "summary": [
                {"label": "Taxable amount", "value": agg["taxable"], "money": True},
                {"label": "Total tax collected", "value": agg["tax"], "money": True},
            ],
        }
