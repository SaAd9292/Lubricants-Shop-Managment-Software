"""Headless structural guard for the Qt views.

PySide6 cannot be imported in CI/sandbox (no libEGL), so a view that *parses*
fine can still be broken at runtime — e.g. a dialog class accidentally inserted
mid-class, which silently re-parents the methods below it onto the wrong class
and crashes the moment the view is constructed. py_compile and pyflakes do NOT
catch that.

This test parses each view with `ast` (no import, no Qt) and asserts that the
expected methods are defined on the expected class. It is deliberately cheap and
import-free so it runs everywhere.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "lubripos" / "views"

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def class_methods(path: Path, cls: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {m.name for m in node.body if isinstance(m, ast.FunctionDef)}
    return set()


# (file, class, [methods that MUST be defined directly on that class])
EXPECTED = [
    ("returns_view.py", "ReturnsView",
     ["_build_ui", "_fetch", "_process", "_no_receipt_return",
      "_reload_history", "_sync_hist_btns", "_selected_return_id",
      "_edit_selected", "_reverse_selected"]),
    ("returns_view.py", "ReturnEditDialog", ["values"]),
    ("cash_recovery_view.py", "CashRecoveryView",
     ["_build_ui", "_record", "_open_history", "_sync_customer", "_on_mode_changed"]),
    ("cash_recovery_view.py", "RecoveryHistoryDialog",
     ["_reload", "_edit", "_reverse", "_sync_btn", "_selected_id"]),
    ("cash_recovery_view.py", "RecoveryEditDialog", ["values", "_reload_accounts"]),
    ("supplier_payments_dialog.py", "SupplierPaymentsDialog",
     ["_build", "_reload", "_sync_btns", "_selected_id", "_reverse", "_edit",
      "_export"]),
    ("supplier_payments_dialog.py", "SupplierPaymentEditDialog",
     ["values", "_on_accept"]),
    ("pos_view.py", "_PartialPayDialog", ["values", "_reload_accounts"]),
]


def main() -> int:
    print("\n[views] methods are defined on the correct class (no split-class bug)")
    for fname, cls, methods in EXPECTED:
        present = class_methods(VIEWS / fname, cls)
        missing = [m for m in methods if m not in present]
        check(not missing, f"{cls} has {len(methods)} expected methods"
              + (f"  — MISSING {missing}" if missing else ""))

    n = sum(_r)
    print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
