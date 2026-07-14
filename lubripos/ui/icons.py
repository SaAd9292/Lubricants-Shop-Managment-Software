"""Crisp, recolorable line icons for the sidebar (SVG rendered to QIcon).

One consistent line style (24x24 grid, 2px stroke, round caps). Icons are
recolored per state: slate when idle, white when the nav item is active.
No emoji, no raster assets.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
    _SVG_OK = True
except Exception:  # QtSvg unavailable -> app still runs, just without icons
    _SVG_OK = False

# Each body is the inner SVG for a 24x24 viewBox (stroke set by make_icon).
_BODIES = {
    "dashboard": '<rect x="3" y="3" width="7" height="7" rx="1.5"/>'
                 '<rect x="14" y="3" width="7" height="7" rx="1.5"/>'
                 '<rect x="3" y="14" width="7" height="7" rx="1.5"/>'
                 '<rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "pos": '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/>'
           '<path d="M2 3 H5 L7 15 H19 L21 7 H6"/>',
    "sales": '<path d="M6 3 H18 V21 L15 19 L12 21 L9 19 L6 21 Z"/>'
             '<path d="M9 8 H15"/><path d="M9 12 H15"/>',
    "products": '<path d="M3 7 L12 3 L21 7 V17 L12 21 L3 17 Z"/>'
                '<path d="M3 7 L12 11 L21 7"/><path d="M12 11 V21"/>',
    "taxonomy": '<path d="M3 12 L12 3 H20 V11 L11 20 Z"/><circle cx="16" cy="8" r="1.3"/>',
    "suppliers": '<path d="M3 6 H15 V16 H3 Z"/><path d="M15 9 H19 L21 12 V16 H15"/>'
                 '<circle cx="7" cy="18" r="1.5"/><circle cx="17" cy="18" r="1.5"/>',
    "purchases": '<path d="M12 3 V13"/><path d="M8 9 L12 13 L16 9"/><path d="M4 17 H20 V20 H4 Z"/>',
    "expenses": '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/>',
    "reports": '<rect x="4" y="11" width="3" height="9"/><rect x="10" y="4" width="3" height="16"/>'
               '<rect x="16" y="14" width="3" height="6"/>',
    "users": '<circle cx="12" cy="8" r="3.5"/>'
             '<path d="M5 20 C5 15 9 14 12 14 C15 14 19 15 19 20"/>',
    "backup": '<ellipse cx="12" cy="6" rx="7" ry="3"/>'
              '<path d="M5 6 V12 C5 13.7 8 15 12 15 C16 15 19 13.7 19 12 V6"/>'
              '<path d="M5 12 V18 C5 19.7 8 21 12 21 C16 21 19 19.7 19 18 V12"/>',
    "settings": '<line x1="4" y1="8" x2="20" y2="8"/><circle cx="9" cy="8" r="2"/>'
                '<line x1="4" y1="16" x2="20" y2="16"/><circle cx="15" cy="16" r="2"/>',
    "trash": '<path d="M4 7 H20"/>'
             '<path d="M9 7 V5 A1 1 0 0 1 10 4 H14 A1 1 0 0 1 15 5 V7"/>'
             '<path d="M6 7 V20 A1 1 0 0 0 7 21 H17 A1 1 0 0 0 18 20 V7"/>'
             '<path d="M10 11 V17"/><path d="M14 11 V17"/>',
    "returns": '<path d="M9 5 L4 10 L9 15"/>'
               '<path d="M4 10 H15 A5 5 0 0 1 15 20 H8"/>',
}

_TPL = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="{color}" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">{body}</svg>')


def make_icon(key: str, color: str, size: int = 40) -> QIcon:
    body = _BODIES.get(key)
    if not body or not _SVG_OK:
        return QIcon()
    svg = _TPL.format(color=color, body=body)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)
