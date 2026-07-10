"""Money helpers. Money is stored everywhere as INTEGER minor units.

Conversion to/from the human decimal representation happens ONLY at the
UI/IO boundary using these helpers. Internal math stays in integers, which
is exact (no floating-point rounding drift across reports).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def to_minor(amount: str | float | Decimal, minor_units: int = 100) -> int:
    """Parse a user-entered amount (e.g. '1500.50') into integer minor units."""
    d = Decimal(str(amount))
    return int((d * minor_units).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor(minor: int, minor_units: int = 100) -> Decimal:
    """Convert integer minor units back to a Decimal major amount."""
    return (Decimal(minor) / Decimal(minor_units)).quantize(
        Decimal(1).scaleb(-_decimals(minor_units))
    )


def format_money(minor: int, symbol: str = "Rs", minor_units: int = 100) -> str:
    """Human-readable string, e.g. format_money(450000) -> 'Rs 4,500.00'."""
    value = from_minor(minor, minor_units)
    dec = _decimals(minor_units)
    return f"{symbol} {value:,.{dec}f}"


def apply_tax(subtotal_minor: int, tax_rate_bps: int, *, inclusive: bool = False) -> tuple[int, int]:
    """Return (taxable_base_minor, tax_minor) given a subtotal and bps rate.

    Exclusive: tax is added on top of subtotal.
    Inclusive: subtotal already contains tax; we back it out.
    """
    if tax_rate_bps <= 0:
        return subtotal_minor, 0
    if inclusive:
        # base = total / (1 + rate); tax = total - base
        base = Decimal(subtotal_minor) * 10_000 / (10_000 + tax_rate_bps)
        base_minor = int(base.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return base_minor, subtotal_minor - base_minor
    tax = Decimal(subtotal_minor) * tax_rate_bps / 10_000
    return subtotal_minor, int(tax.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_markup(cost_minor: int, markup_bps: int, round_to_minor: int = 1) -> int:
    """Sale price (minor units) = cost marked up by markup_bps, then rounded.

    markup_bps is basis points over cost (2000 = +20%). round_to_minor is the
    rounding step in MINOR units: pass the currency's minor_units (e.g. 100) to
    round to the nearest whole currency unit (Rs 1). Half-up rounding.
    """
    if cost_minor <= 0 or markup_bps <= 0:
        return max(0, int(cost_minor))
    raw = Decimal(cost_minor) * (10_000 + markup_bps) / 10_000
    step = max(1, int(round_to_minor))
    # round raw to the nearest multiple of `step`
    units = (raw / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(units) * step


def _decimals(minor_units: int) -> int:
    return max(0, len(str(minor_units)) - 1)
