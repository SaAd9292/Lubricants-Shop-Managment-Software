"""Headless tests: fuzzy 'similar product already exists' duplicate guard."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.services.product_service import ProductService

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c))
    print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    ctx = AppContext(Config(data_root=Path(tempfile.mkdtemp())))
    ps = ProductService(ctx.db, ctx.audit)
    mid = ps.create({"name": "ZIC M5 20W-50 4L", "sale_price_minor": 100})
    ps.create({"name": "ZIC X7 10W-40 1L", "sale_price_minor": 100})

    def names(q, **kw):
        return [m["name"] for m in ps.find_similar(q, **kw)]

    print("\n[similar] spelling / spacing / suffix variants match")
    check(names("zic m-5 20w50 4l") == ["ZIC M5 20W-50 4L"], "dash/spacing variant matches")
    check(names("ZIC M5 20W50 4Ltr") == ["ZIC M5 20W-50 4L"], "'Ltr' suffix variant matches")
    check(names("ZIC  M5  20W-50  4L") == ["ZIC M5 20W-50 4L"], "extra spaces match")

    print("\n[similar] genuinely different products do NOT match")
    check(names("ZIC X9 5W-40 1L") == [], "different grade -> no match")
    check(names("Shell Helix 5W-30") == [], "different brand -> no match")

    print("\n[similar] safeguards")
    check(ps.find_similar("ZIC M5 20W-50 4L", exclude_id=mid) == [],
          "editing a product doesn't flag itself")
    check(ps.find_similar("ab") == [], "too-short input returns nothing")

    total, passed = len(_r), sum(_r)
    print(f"\n[similar] {passed}/{total} checks passed\n")
    ctx.shutdown()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
