"""Tests for the auto-updater: version compare + signed-manifest verification.
No network — the manifest fetch is monkeypatched, and a throwaway keypair is used."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lubripos.core import ed25519
from lubripos.services import update_service as us

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_r: list[bool] = []


def check(c, label):
    _r.append(bool(c)); print(f"  {PASS if c else FAIL}  {label}")


def main() -> int:
    print("\n[update] version comparison")
    check(us.is_newer("0.5.1", "0.5.0"), "0.5.1 > 0.5.0")
    check(us.is_newer("1.0.0", "0.9.9"), "1.0.0 > 0.9.9")
    check(not us.is_newer("0.5.0", "0.5.0"), "equal is not newer")
    check(not us.is_newer("0.4.0", "0.5.0"), "older is not newer")
    check(us.is_newer("v0.5.1", "0.5.0"), "tolerates a 'v' prefix")

    print("\n[update] signed-manifest verification")
    seed, pub = ed25519.generate_keypair()
    svc = us.UpdateService(ctx=None)
    svc._pubkey = pub
    data = {"version": "9.9.9", "url": "http://x/setup.exe",
            "sha256": "ab" * 32, "notes": "new"}
    sig = ed25519.sign(us._canonical(data), seed).hex()
    check(svc._verify_manifest({"data": data, "sig": sig})["version"] == "9.9.9",
          "valid signature accepted")
    try:
        svc._verify_manifest({"data": {**data, "url": "http://evil"}, "sig": sig})
        check(False, "tampered manifest should raise")
    except us.UpdateError:
        check(True, "tampered manifest rejected")
    try:
        svc._verify_manifest({"data": data, "sig": "00" * 64})
        check(False, "forged signature should raise")
    except us.UpdateError:
        check(True, "forged signature rejected")

    print("\n[update] check() end-to-end (monkeypatched fetch)")
    svc._fetch_manifest = lambda: {"data": data, "sig": sig}
    info = svc.check()
    check(info and info["version"] == "9.9.9" and info["sha256"] == "ab" * 32,
          "newer verified version returns info")
    older = {"version": "0.0.1", "url": "http://x/s.exe", "sha256": "cd" * 32, "notes": ""}
    svc._fetch_manifest = lambda: {"data": older,
                                   "sig": ed25519.sign(us._canonical(older), seed).hex()}
    check(svc.check() is None, "up-to-date returns None")
    svc._fetch_manifest = lambda: {"data": data, "sig": "11" * 64}
    try:
        svc.check(); check(False, "bad sig in check() should raise")
    except us.UpdateError:
        check(True, "check() raises on bad signature")

    print("\n[update] daily throttle uses a file, not the DB (no thread crash)")
    import tempfile, types
    ctx = types.SimpleNamespace(config=types.SimpleNamespace(data_root=tempfile.mkdtemp()))
    svc2 = us.UpdateService(ctx)
    check(svc2.should_check_today(), "fresh install -> should check")
    svc2.mark_checked()
    check(not svc2.should_check_today(), "after marking -> throttled for the day")

    n = sum(_r); print(f"\n==== {n}/{len(_r)} checks passed ====")
    return 0 if n == len(_r) else 1


if __name__ == "__main__":
    sys.exit(main())
