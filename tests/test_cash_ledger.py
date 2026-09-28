"""Headless tests: the Cash in Hand Ledger (cash book) report.

Every cash movement in the range appears once; a running balance from the
opening float ties out exactly to CashService.balance_as_of(range end).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core.session import CurrentUser, current_session
from lubripos.services.product_service import ProductService
from lubripos.services.supplier_service import SupplierService
from lubripos.services.report_service import ReportService
from lubripos.services.cash_service import CashService
from lubripos.controllers.sale_controller import SaleController
from lubripos.controllers.purchase_controller import PurchaseController
from lubripos.reports.report_exporter import to_pdf, to_xlsx

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    current_session.login(CurrentUser(id=1, username="a", full_name="A", role="admin"))
    ctx.company.update_tax({"tax_enabled": 0})
    ps = ProductService(ctx.db, ctx.audit)
    sc = SaleController(ctx)
    pc = PurchaseController(ctx)
    rs = ReportService(ctx.db)
    cash = CashService(ctx.db)

    A = ps.create({"name": "Oil", "sale_price_minor": 100000,
                   "purchase_price_minor": 60000, "stock_qty": 1000})
    sup = SupplierService(ctx.db, ctx.audit).create({"name": "Dist"})

    ctx.company.update_company({"cash_opening_minor": 500000,        # Rs 5,000
                                "cash_opening_date": "2026-03-01"})

    # movements inside March 2026
    sc.record_backdated_sale(lines=[{"product_id": A, "qty": 3, "unit_price": 1000}],
                             sale_date="2026-03-02", payment_method="Cash")   # +3000
    sc.record_backdated_sale(lines=[{"product_id": A, "qty": 1, "unit_price": 1000}],
                             sale_date="2026-03-02", payment_method="Bank")   # not cash
    ctx.db.execute("INSERT INTO expenses (category, amount_minor, expense_date, created_by) "
                   "VALUES ('Rent', 200000, '2026-03-03 09:00:00', 1)")        # -2000
    pc.create(supplier_id=sup, amount_paid=1000, purchase_date="2026-03-04",
              lines=[{"product_id": A, "qty": 5, "unit_cost": 400}])           # -1000

    print("\n[cashledger] ledger ties out to the running balance")
    rep = rs.cash_ledger("2026-03-01", "2026-03-31")
    summ = {s["label"]: s["value"] for s in rep["summary"]}
    check(summ["Opening balance"] == 500000, "opening = float Rs 5,000")
    check(summ["Total cash in"] == 300000, "total cash in = Rs 3,000 (bank sale excluded)")
    check(summ["Total cash out"] == 300000, "total cash out = 2,000 expense + 1,000 purchase")
    check(summ["Closing (Cash in Hand)"] == 500000,
          "closing = 5,000 + 3,000 - 3,000 = Rs 5,000")
    check(summ["Closing (Cash in Hand)"] == cash.balance_as_of("2026-03-31"),
          "closing equals CashService.balance_as_of(range end)")

    print("\n[cashledger] rows: opening + one per movement (bank sale excluded)")
    # 1 opening + cash sale + expense + purchase payment = 4 rows
    check(len(rep["rows"]) == 4, f"4 rows (got {len(rep['rows'])})")
    check(rep["rows"][0]["details"] == "Opening balance", "first row is opening")
    kinds = " ".join(r["details"] for r in rep["rows"])
    check("Sale" in kinds and "Expense" in kinds and "Purchase payment" in kinds,
          "sale, expense and purchase payment each listed")
    check("Bank" not in kinds, "the bank sale is NOT in the cash ledger")

    print("\n[cashledger] renders to PDF + Excel")
    company = ctx.company.get_company()
    d = tempfile.mkdtemp()
    p1 = to_pdf(rep, company, os.path.join(d, "cash.pdf"))
    p2 = to_xlsx(rep, company, os.path.join(d, "cash.xlsx"))
    check(os.path.getsize(p1) > 800, "PDF generated")
    check(os.path.getsize(p2) > 800, "XLSX generated")

    print("\n[cashledger] empty range is safe")
    rep2 = rs.cash_ledger("2025-01-01", "2025-01-31")
    check(len(rep2["rows"]) == 1, "empty range shows just the opening row")

    total, passed = len(_r), sum(_r)
    print(f"\n[cashledger] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
