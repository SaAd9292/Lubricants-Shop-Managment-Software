"""Password hashing using the Python standard library (PBKDF2-HMAC-SHA256).

Why PBKDF2 and not argon2:
  * Zero external dependency -> clean PyInstaller builds on every OS.
  * Standard-library, well-vetted, FIPS-friendly.
PBKDF2 is production-acceptable for a local desktop POS. To upgrade to
argon2id later, only the three functions below need to change; storage
already records the algorithm parameters per user (salt + iterations).

Each user gets a unique random salt. Verification is constant-time.
"""
from __future__ import annotations

import hashlib
import hmac
import os

ALGO = "sha256"
DEFAULT_ITERATIONS = 240_000
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> tuple[str, str, int]:
    """Return (hash_hex, salt_hex, iterations) for storing a new password."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(ALGO, password.encode("utf-8"), salt, iterations)
    return dk.hex(), salt.hex(), iterations


def verify_password(password: str, hash_hex: str, salt_hex: str, iterations: int) -> bool:
    """Constant-time verification of a candidate password against stored values."""
    if not password or not hash_hex or not salt_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(ALGO, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)
