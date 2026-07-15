"""Tests for the language toggle + touch-mode settings and the tr() layer."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.app_context import AppContext
from lubripos.config import Config
from lubripos.core import i18n

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c)); print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    print("\n[i18n] tr() translate + fallback")
    i18n.set_language("ur")
    check(i18n.current_language() == "ur", "language set to ur")
    check(i18n.tr("Sale") == "فروخت", "known string translated")
    check(i18n.tr("Complete Sale  (F2)").startswith("فروخت"), "POS button translated")
    check(i18n.tr("Zzz Not A Real String") == "Zzz Not A Real String",
          "unknown string falls back to English")
    i18n.set_language("en")
    check(i18n.tr("Sale") == "Sale", "English returns English")
    i18n.set_language("xx")
    check(i18n.current_language() == "en", "unknown language -> English")

    print("\n[i18n] settings persist language + touch_mode")
    cfg = Config(data_root=Path(tempfile.mkdtemp())); cfg.ensure_dirs()
    ctx = AppContext(config=cfg)
    ver = int(ctx.db.query_one("SELECT value FROM app_meta WHERE key='schema_version'")["value"])
    check(ver >= 10, f"schema_version >= 10 (got {ver})")
    c0 = ctx.company.get_company()
    check(c0.get("language") == "en" and c0.get("touch_mode") == 0,
          "defaults: English, touch off")
    ctx.company.update_company({"language": "ur", "touch_mode": 1})
    c1 = ctx.company.get_company()
    check(c1["language"] == "ur" and c1["touch_mode"] == 1, "settings saved")
    ctx.shutdown()

    n = sum(_r); print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
