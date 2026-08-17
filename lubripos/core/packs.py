"""Carton / loose-piece helpers.

Stock is stored as a single piece (bottle) count. Shops think in cartons + loose
pieces, where a carton holds `units_per_carton` pieces (from the product). These
helpers convert between the two views so the UI and reports can show, e.g.,
"3 ctn + 9 pc" while the database keeps 45.
"""
from __future__ import annotations


def split_packs(qty, units_per_carton) -> tuple[int, int]:
    """Return (cartons, loose_pieces) for a piece count. units_per_carton < 2
    means the product isn't sold in cartons -> (0, qty)."""
    upc = max(1, int(units_per_carton or 1))
    q = max(0, int(qty or 0))
    if upc <= 1:
        return 0, q
    return divmod(q, upc)


def name_with_pack(name, pack_size) -> str:
    """Ensure a product name ends with its pack size, e.g.
    ('S-oil 0W-20', '4 L') -> 'S-oil 0W-20 4L'. Spaces in the pack are removed
    ('3.8 L' -> '3.8L'). Idempotent: if the name already ends with the pack
    (ignoring spaces/case) it is returned unchanged, so re-saving never doubles
    it up."""
    name = (name or "").strip()
    suffix = "".join(str(pack_size or "").split())  # '4 L' -> '4L'
    if not suffix:
        return name
    if name.replace(" ", "").lower().endswith(suffix.lower()):
        return name
    return f"{name} {suffix}".strip()


def fmt_packs(qty, units_per_carton) -> str:
    """Human display of a piece count as cartons + loose pieces.
    upc<2 -> just the number (e.g. drums, loose items)."""
    upc = max(1, int(units_per_carton or 1))
    q = max(0, int(qty or 0))
    if upc <= 1:
        return str(q)
    cartons, loose = divmod(q, upc)
    if cartons and loose:
        return f"{cartons} ctn + {loose} pc"
    if cartons:
        return f"{cartons} ctn"
    return f"{loose} pc"
