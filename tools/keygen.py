"""Generate a NEW Ed25519 update-signing keypair.

Run ONLY to create the first key or to rotate keys. Writes the private seed to
keys/update_private_seed.hex (git-ignored) and prints the PUBLIC key hex to paste
into lubripos/services/update_config.py (UPDATE_PUBLIC_KEY_HEX).

    python tools/keygen.py

WARNING: rotating the key means old installs (shipping the old public key) will
reject manifests signed with the new key until they update once by other means.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lubripos.core import ed25519  # noqa: E402

keys_dir = Path(__file__).resolve().parents[1] / "keys"
keys_dir.mkdir(exist_ok=True)
seed_file = keys_dir / "update_private_seed.hex"
if seed_file.exists():
    print(f"Refusing to overwrite existing key: {seed_file}")
    print("Delete it first if you really intend to rotate.")
    raise SystemExit(1)

seed, pub = ed25519.generate_keypair()
seed_file.write_text(seed.hex() + "\n")
try:
    seed_file.chmod(0o600)
except OSError:
    pass
print("Private seed written to:", seed_file, "(KEEP SECRET, back it up, never commit)")
print("\nPaste this into lubripos/services/update_config.py:")
print(f'UPDATE_PUBLIC_KEY_HEX = "{pub.hex()}"')
