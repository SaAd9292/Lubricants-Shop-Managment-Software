"""Self-contained Ed25519 (RFC 8032) — sign & verify, pure Python, stdlib only.

Used to sign the auto-update manifest offline (release.py) and verify it inside
the app (update_service). Kept dependency-free on purpose: no cryptography /
OpenSSL to bundle into the PyInstaller build. This is the canonical reference
implementation (public domain), wrapped in a small, friendly API.

Security notes:
  * The PRIVATE seed never ships with the app — only the 32-byte public key.
  * verify() returns False on ANY problem (bad length, malformed point, bad
    signature); it never raises, so callers can treat False as "reject".
"""
from __future__ import annotations

import hashlib
import os

_b = 256
_q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _expmod(base: int, e: int, m: int) -> int:
    return pow(base, e, m)


def _inv(x: int) -> int:
    return pow(x, _q - 2, _q)


_d = -121665 * _inv(121666) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = 4 * _inv(5) % _q
_Bx = _xrecover(_By)
_B = [_Bx % _q, _By % _q]


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2) % _q
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2) % _q
    return [x3 % _q, y3 % _q]


def _scalarmult(P, e: int):
    if e == 0:
        return [0, 1]
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _encodeint(y: int) -> bytes:
    bits = [(y >> i) & 1 for i in range(_b)]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8))


def _encodepoint(P) -> bytes:
    x, y = P
    bits = [(y >> i) & 1 for i in range(_b - 1)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8))


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _secret_scalar(sk: bytes) -> int:
    h = _H(sk)
    return 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))


def publickey(sk: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret seed."""
    a = _secret_scalar(sk)
    return _encodepoint(_scalarmult(_B, a))


def _Hint(m: bytes) -> int:
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * _b))


def signature(m: bytes, sk: bytes, pk: bytes) -> bytes:
    """Return the 64-byte signature of message m for seed sk / public key pk."""
    h = _H(sk)
    a = _secret_scalar(sk)
    r = _Hint(h[_b // 8:_b // 4] + m)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pk + m) * a) % _L
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P) -> bool:
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _decodeint(s: bytes) -> int:
    return sum(2 ** i * _bit(s, i) for i in range(_b))


def _decodepoint(s: bytes):
    y = sum(2 ** i * _bit(s, i) for i in range(_b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, _b - 1):
        x = _q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("point not on curve")
    return P


def _checkvalid(sig: bytes, m: bytes, pk: bytes) -> bool:
    if len(sig) != _b // 4 or len(pk) != _b // 8:
        return False
    R = _decodepoint(sig[:_b // 8])
    A = _decodepoint(pk)
    S = _decodeint(sig[_b // 8:_b // 4])
    return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, _Hint(_encodepoint(R) + pk + m)))


# ---- friendly public API ------------------------------------------------
def generate_keypair() -> tuple[bytes, bytes]:
    """Return (seed32, public32). Keep the seed secret; ship only the public."""
    seed = os.urandom(32)
    return seed, publickey(seed)


def sign(message: bytes, seed: bytes) -> bytes:
    """Sign message with a 32-byte seed; returns a 64-byte signature."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    return signature(message, seed, publickey(seed))


def verify(message: bytes, sig: bytes, public_key: bytes) -> bool:
    """True iff sig is a valid Ed25519 signature of message under public_key.
    Never raises — returns False on any malformed input."""
    try:
        return _checkvalid(sig, message, public_key)
    except Exception:
        return False
