"""Cash-in-hand: the running physical-drawer balance.

This is the single source of truth for how much cash is in the till at any
point in time. It is DERIVED, never stored as a mutable counter — a stored
counter drifts the moment anything is edited, deleted, or back-dated, with no
way to recover the true value. Here the balance is always recomputed from an
opening float plus the cash movements that already live in their own tables, so
it can never desync and is fully auditable.

    balance(as of D) = opening_float
                     + cash sales            (sales, method=Cash, completed)
                     + cash debt repayments  (customer_payments, method=Cash/NULL)
                     - cash refunds           (sale_returns, method=Cash/NULL)
                     - expenses               (all expenses are cash out)
                     - purchase payments      (purchases.amount_paid, cash from till)
                     - supplier payments      (supplier_payments, cash from till)

Only movements dated on/after `cash_opening_date` are counted; earlier history
is considered baked into the opening float, so it is never double-counted.

NOTE on supplier/purchase payments: per the shop's setup, EVERY supplier
payment is treated as cash paid out of this same drawer, regardless of any
method recorded on the payment. If a shop starts paying suppliers by bank, this
is the one assumption to revisit (add a per-payment method filter here).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..database.connection import Database


class CashService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- opening float ------------------------------------------------
    def _opening(self) -> tuple[int, str | None]:
        """(opening_float_minor, opening_date or None)."""
        row = self.db.query_one(
            "SELECT cash_opening_minor, cash_opening_date "
            "FROM company_settings WHERE id = 1")
        if not row:
            return 0, None
        return int(row["cash_opening_minor"] or 0), (row["cash_opening_date"] or None)

    # -- generic dated sum -------------------------------------------
    def _sum(self, table: str, amount_col: str, date_col: str,
             d_from: str | None, d_to: str | None, extra: str = "") -> int:
        """SUM(amount_col) over rows whose DATE part is within [d_from, d_to]
        (either bound optional, both inclusive), plus an optional extra SQL
        predicate. Dates are stored as 'YYYY-MM-DD HH:MM:SS'; we compare on the
        10-char date prefix so a time component never excludes a row."""
        conds: list[str] = []
        params: list[Any] = []
        if d_from:
            conds.append(f"substr({date_col},1,10) >= ?"); params.append(d_from)
        if d_to:
            conds.append(f"substr({date_col},1,10) <= ?"); params.append(d_to)
        if extra:
            conds.append(extra)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        return int(self.db.query_one(
            f"SELECT COALESCE(SUM({amount_col}),0) v FROM {table}{where}",
            tuple(params))["v"])

    # -- cash movement components (all as positive amounts) ----------
    def _cash_sales(self, d_from, d_to) -> int:
        return self._sum("sales", "grand_total_minor", "sale_date", d_from, d_to,
                         "status='completed' AND LOWER(payment_method)='cash'")

    def _cash_repayments(self, d_from, d_to) -> int:
        return self._sum("customer_payments", "amount_minor", "payment_date",
                         d_from, d_to, "COALESCE(method,'Cash')='Cash'")

    def _cash_refunds(self, d_from, d_to) -> int:
        conds = ["COALESCE(sr.method,'Cash')='Cash'"]
        params: list[Any] = []
        if d_from:
            conds.append("substr(sr.return_date,1,10) >= ?"); params.append(d_from)
        if d_to:
            conds.append("substr(sr.return_date,1,10) <= ?"); params.append(d_to)
        where = " WHERE " + " AND ".join(conds)
        return int(self.db.query_one(
            "SELECT COALESCE(SUM(sri.line_total_minor),0) v "
            "FROM sale_return_items sri JOIN sale_returns sr ON sr.id = sri.return_id"
            + where, tuple(params))["v"])

    def _expenses(self, d_from, d_to) -> int:
        return self._sum("expenses", "amount_minor", "expense_date", d_from, d_to)

    def _purchase_payments(self, d_from, d_to) -> int:
        return self._sum("purchases", "amount_paid_minor", "purchase_date",
                         d_from, d_to)

    def _supplier_payments(self, d_from, d_to) -> int:
        return self._sum("supplier_payments", "amount_minor", "payment_date",
                         d_from, d_to)

    # -- public: point-in-time balance -------------------------------
    def balance_as_of(self, as_of: str | None = None) -> int:
        """Running cash in the drawer at the end of `as_of` (YYYY-MM-DD, default
        today). = opening float + all cash movements in [opening_date, as_of]."""
        as_of = (as_of or date.today().isoformat())[:10]
        opening, o_date = self._opening()
        d_from = o_date
        cash_in = (self._cash_sales(d_from, as_of)
                   + self._cash_repayments(d_from, as_of))
        cash_out = (self._cash_refunds(d_from, as_of)
                    + self._expenses(d_from, as_of)
                    + self._purchase_payments(d_from, as_of)
                    + self._supplier_payments(d_from, as_of))
        return opening + cash_in - cash_out

    def current(self) -> int:
        """TOTAL business cash in hand right now (the running ledger through end
        of today). This accumulates across days — it is NOT what a single day's
        drawer holds; for the end-of-day drawer count use `todays_takings`."""
        return self.balance_as_of(date.today().isoformat())

    def todays_takings(self, day: str | None = None) -> int:
        """The cash that flowed through the drawer on a single day: that day's
        cash in (cash sales + cash recoveries) minus that day's cash out (cash
        refunds, expenses, purchase + supplier payments). Independent of the
        running total and the opening float — this is what an end-of-day drawer
        count is checked against (the day's takings, drawer emptied each day)."""
        r = self.reconciliation((day or date.today().isoformat())[:10])
        return r["cash_in"] - r["cash_out"]

    def opening_before(self, day: str) -> int:
        """Running cash at the START of `day` = the closing balance of the day
        before it. Used as the opening balance of a ledger range."""
        d = date.fromisoformat(day[:10]) - timedelta(days=1)
        return self.balance_as_of(d.isoformat())

    # -- end-of-day drawer count ------------------------------------
    def record_count(self, counted_minor: int, *, day: str | None = None,
                     expected_minor: int | None = None, notes: str | None = None,
                     user_id: int | None = None) -> dict:
        """Record a physical drawer count for a given day (default today).
        `expected` defaults to that DAY'S cash takings (its cash in minus cash
        out — the single-day drawer figure, not the total business cash).
        difference = counted - expected (positive = over, negative = short).
        Record only — it does NOT change Cash in Hand, so a real discrepancy
        stays visible."""
        day = (day or date.today().isoformat())[:10]
        counted = int(counted_minor)
        expected = (self.todays_takings(day) if expected_minor is None
                    else int(expected_minor))
        diff = counted - expected
        cur = self.db.execute(
            "INSERT INTO cash_counts (count_date, counted_minor, expected_minor, "
            "difference_minor, notes, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (day, counted, expected, diff, (notes or "").strip() or None, user_id))
        return {"id": cur.lastrowid, "count_date": day, "counted_minor": counted,
                "expected_minor": expected, "difference_minor": diff}

    def last_count(self) -> dict | None:
        row = self.db.query_one(
            "SELECT count_date, counted_minor, expected_minor, difference_minor, "
            "notes, counted_at FROM cash_counts ORDER BY id DESC LIMIT 1")
        return dict(row) if row else None

    # -- itemised movements (for the cash-in-hand ledger) ------------
    def movements(self, d_from: str, d_to: str) -> list[dict[str, Any]]:
        """Every individual cash movement in [d_from, d_to] (inclusive dates),
        date-ordered. Each item: {date, details, cash_in, cash_out} in minor
        units (one side is 0). Mirrors exactly what balance_as_of counts, so a
        running balance over these ties out to the closing balance."""
        d_from, d_to = d_from[:10], d_to[:10]
        rng = (d_from, d_to)
        out: list[dict[str, Any]] = []

        def add(dt, details, cin, cout):
            out.append({"date": dt, "details": details,
                        "cash_in": int(cin or 0), "cash_out": int(cout or 0)})

        for r in self.db.query(
            "SELECT sale_date d, invoice_no ref, grand_total_minor amt FROM sales "
            "WHERE status='completed' AND LOWER(payment_method)='cash' "
            "AND substr(sale_date,1,10) BETWEEN ? AND ?", rng):
            add(r["d"], f"Sale {r['ref']}", r["amt"], 0)

        for r in self.db.query(
            "SELECT cp.payment_date d, COALESCE(c.name,'(customer)') nm, "
            "cp.amount_minor amt FROM customer_payments cp "
            "LEFT JOIN customers c ON c.id = cp.customer_id "
            "WHERE COALESCE(cp.method,'Cash')='Cash' "
            "AND substr(cp.payment_date,1,10) BETWEEN ? AND ?", rng):
            add(r["d"], f"Recovery — {r['nm']}", r["amt"], 0)

        for r in self.db.query(
            "SELECT sr.return_date d, sr.refund_minor amt, s.invoice_no inv "
            "FROM sale_returns sr LEFT JOIN sales s ON s.id = sr.sale_id "
            "WHERE COALESCE(sr.method,'Cash')='Cash' "
            "AND substr(sr.return_date,1,10) BETWEEN ? AND ?", rng):
            det = f"Refund {r['inv']}" if r["inv"] else "Refund (no receipt)"
            add(r["d"], det, 0, r["amt"])

        for r in self.db.query(
            "SELECT expense_date d, category cat, COALESCE(description,'') ds, "
            "amount_minor amt FROM expenses "
            "WHERE substr(expense_date,1,10) BETWEEN ? AND ?", rng):
            det = f"Expense — {r['cat']}" + (f" ({r['ds']})" if r["ds"] else "")
            add(r["d"], det, 0, r["amt"])

        for r in self.db.query(
            "SELECT p.purchase_date d, p.amount_paid_minor amt, "
            "p.supplier_invoice_no inv, s.name snm FROM purchases p "
            "LEFT JOIN suppliers s ON s.id = p.supplier_id "
            "WHERE p.amount_paid_minor > 0 "
            "AND substr(p.purchase_date,1,10) BETWEEN ? AND ?", rng):
            det = "Purchase payment" + (f" — {r['snm']}" if r["snm"] else "") \
                  + (f" ({r['inv']})" if r["inv"] else "")
            add(r["d"], det, 0, r["amt"])

        for r in self.db.query(
            "SELECT sp.payment_date d, sp.amount_minor amt, s.name snm "
            "FROM supplier_payments sp LEFT JOIN suppliers s ON s.id = sp.supplier_id "
            "WHERE substr(sp.payment_date,1,10) BETWEEN ? AND ?", rng):
            add(r["d"], "Supplier payment" + (f" — {r['snm']}" if r["snm"] else ""),
                0, r["amt"])

        out.sort(key=lambda x: x["date"])
        return out

    # -- public: one day's reconciliation ----------------------------
    def reconciliation(self, day: str) -> dict[str, int]:
        """Opening -> movements -> closing for a single day, so a Day-Close sheet
        reconciles: closing of day D is the opening of day D+1.

        Returns each component (all positive) plus opening, cash_in, cash_out,
        and closing (= cash in hand at end of the day)."""
        day = day[:10]
        cash_sales = self._cash_sales(day, day)
        repayments = self._cash_repayments(day, day)
        refunds = self._cash_refunds(day, day)
        expenses = self._expenses(day, day)
        purchase_pay = self._purchase_payments(day, day)
        supplier_pay = self._supplier_payments(day, day)
        cash_in = cash_sales + repayments
        cash_out = refunds + expenses + purchase_pay + supplier_pay
        closing = self.balance_as_of(day)
        opening = closing - cash_in + cash_out
        return {
            "opening": opening,
            "cash_sales": cash_sales,
            "repayments": repayments,
            "refunds": refunds,
            "expenses": expenses,
            "purchase_payments": purchase_pay,
            "supplier_payments": supplier_pay,
            "cash_in": cash_in,
            "cash_out": cash_out,
            "closing": closing,
        }
