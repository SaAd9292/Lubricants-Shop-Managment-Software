"""Tiny runtime translation layer.

Design choice: a plain Python dict rather than Qt's .ts/.qm machinery. For a
single-maintainer shop app this is far easier to extend (just add a line) and
lets us switch language from a setting without compiling translation files.

Urdu is shown left-to-right (the app does NOT mirror the layout) so no screen
re-flows — a deliberate trade of authenticity for zero layout risk.

Only cashier-facing strings are translated for now (sidebar, POS/Sale, common
buttons and messages, receipt). Any string with no entry falls back to English,
so partial coverage is safe. NOTE: the Urdu below is serviceable but should be
reviewed by a native speaker before shipping to customers.

Usage:  from ..core.i18n import tr    ...    QLabel(tr("Complete Sale"))
"""
from __future__ import annotations

_lang = "en"

# English -> Urdu. Extend freely; missing keys fall back to the English text.
_UR: dict[str, str] = {
    # -- sidebar / navigation --
    "Dashboard": "ڈیش بورڈ",
    "Sale": "فروخت",
    "Sales History": "فروخت کی تاریخ",
    "Returns": "واپسی",
    "Customers": "گاہک",
    "Products": "پروڈکٹس",
    "Categories & Brands": "اقسام اور برانڈز",
    "Suppliers": "سپلائرز",
    "Purchases": "خریداری",
    "Payables": "واجب الادا",
    "Expenses": "اخراجات",
    "Reports": "رپورٹس",
    "Users": "صارفین",
    "Audit Log": "آڈٹ لاگ",
    "Backup & Restore": "بیک اپ اور بحالی",
    "Settings": "ترتیبات",
    "Log out": "لاگ آؤٹ",
    # -- POS / Sale --
    "Sale (POS)": "فروخت (پی او ایس)",
    "Scan barcode…": "بارکوڈ اسکین کریں…",
    "Search": "تلاش کریں",
    "Search products…": "پروڈکٹ تلاش کریں…",
    "Clear": "صاف کریں",
    "Bill Summary": "بل کا خلاصہ",
    "Subtotal": "ذیلی رقم",
    "Discount": "رعایت",
    "Tax": "ٹیکس",
    "Grand Total": "کل رقم",
    "Payment": "ادائیگی",
    "Account": "اکاؤنٹ",
    "Customer (optional)": "گاہک (اختیاری)",
    "Name": "نام",
    "Phone": "فون",
    "Find": "تلاش کریں",
    "Complete Sale  (F2)": "فروخت مکمل کریں (F2)",
    "Cart is empty.": "کارٹ خالی ہے۔",
    "Cash": "نقد",
    "Bank": "بینک",
    # -- common buttons / labels --
    "Save": "محفوظ کریں",
    "Cancel": "منسوخ کریں",
    "Edit": "ترمیم",
    "Delete": "حذف کریں",
    "Remove": "ہٹا دیں",
    "Add": "شامل کریں",
    "Close": "بند کریں",
    "Print": "پرنٹ کریں",
    "Add to sale": "فروخت میں شامل کریں",
    "Quantity": "مقدار",
    "Qty": "مقدار",
    "Price": "قیمت",
    "Total": "کل",
    "Date": "تاریخ",
    "Invoice": "رسید",
    "Product": "پروڈکٹ",
    "Amount": "رقم",
    "Scan barcode and press Enter…": "بارکوڈ اسکین کریں اور Enter دبائیں…",
    "Search product": "پروڈکٹ تلاش کریں",
    "Clear cart": "کارٹ صاف کریں",
    "Item": "آئٹم",
    "Line Total": "لائن کل",
    "Add Customer": "گاہک شامل کریں",
    "Find customer": "گاہک تلاش کریں",
    "Search by name or phone…": "نام یا فون سے تلاش کریں…",
    "Reorder": "دوبارہ آرڈر",
    "Tick the products to add to this sale:": "اس فروخت میں شامل کرنے کے لیے پروڈکٹ منتخب کریں:",
    # -- receipt --
    "Cashier": "کیشئر",
    "Status": "حالت",
    "Customer": "گاہک",
    "Thank you": "شکریہ",
}

_TABLES = {"en": {}, "ur": _UR}


def set_language(lang: str | None) -> None:
    """Set the active UI language ('en' or 'ur'). Unknown -> English."""
    global _lang
    _lang = "ur" if str(lang).lower() in ("ur", "urdu") else "en"


def current_language() -> str:
    return _lang


def tr(text: str) -> str:
    """Translate a UI string to the active language, falling back to English."""
    if _lang == "en":
        return text
    return _TABLES.get(_lang, {}).get(text, text)
