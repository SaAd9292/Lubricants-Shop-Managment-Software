"""Cut a Penguix release: build the signed update manifest (latest.json).

Prereqs: you have already built the installer (build_installer.bat) so the .exe
exists, and keys/update_private_seed.hex holds the private seed.

    python tools/release.py --installer installer/output/Penguix-Setup-0.5.0.exe \
                            --notes "Returns, payables, customers, Urdu, updates"

Steps performed:
  1. read version from lubripos/__init__.py
  2. sha256 the installer
  3. build manifest {version,url,sha256,notes} where url points at the versioned
     GitHub release asset
  4. Ed25519-sign the canonical manifest with the private seed
  5. write dist/latest.json

Then publish BOTH files as assets on a GitHub Release tagged v<version>:
  gh release create v<version> "<installer>" dist/latest.json --title "v<version>" --notes "<notes>"
(so https://.../releases/latest/download/latest.json resolves to this manifest).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lubripos.core import ed25519  # noqa: E402
from lubripos.services.update_config import MANIFEST_URL  # noqa: E402


def _version() -> str:
    text = (ROOT / "lubripos" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("Could not read __version__ from lubripos/__init__.py")
    return m.group(1)


def _repo_base() -> str:
    # MANIFEST_URL = https://github.com/<owner>/<repo>/releases/latest/download/latest.json
    return MANIFEST_URL.split("/releases/")[0]


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", required=True, help="path to the built .exe")
    ap.add_argument("--notes", default="", help="release notes shown to users")
    args = ap.parse_args()

    installer = Path(args.installer)
    if not installer.exists():
        raise SystemExit(f"Installer not found: {installer}")
    seed_file = ROOT / "keys" / "update_private_seed.hex"
    if not seed_file.exists():
        raise SystemExit(f"Missing signing key: {seed_file} (run tools/keygen.py)")
    seed = bytes.fromhex(seed_file.read_text().strip())

    version = _version()
    sha256 = hashlib.sha256(installer.read_bytes()).hexdigest()
    url = f"{_repo_base()}/releases/download/v{version}/{installer.name}"
    data = {"version": version, "url": url, "sha256": sha256, "notes": args.notes}
    sig = ed25519.sign(_canonical(data), seed).hex()

    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "latest.json"
    out.write_text(json.dumps({"data": data, "sig": sig}, indent=2), encoding="utf-8")

    print(f"Wrote {out}")
    print(f"  version : {version}")
    print(f"  sha256  : {sha256}")
    print(f"  url     : {url}")
    print("\nPublish the release (installer + manifest) with:")
    print(f'  gh release create v{version} "{installer}" "{out}" '
          f'--title "v{version}" --notes "{args.notes or version}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
