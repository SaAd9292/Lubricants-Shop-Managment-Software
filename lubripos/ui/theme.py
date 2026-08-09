"""Native Windows styling for Penguix, with a clear button hierarchy.

Standard controls (inputs, tables, combo boxes, date pickers, scrollbars) are
left UNSTYLED so Qt renders them with the platform-native look. We add a thin
chrome layer for the sidebar/header/cards, and — for a more professional feel —
a primary/secondary BUTTON system:

  * primary buttons (default) get the accent fill: one clear call-to-action per
    screen (Add..., Generate, Save, Complete Sale, Back up now, ...).
  * secondary buttons (objectName "Secondary") are quiet outlined buttons
    (Edit, Remove, pagination, inline "+", etc.).

The codebase already tags subordinate buttons as "Secondary", so this hierarchy
applies automatically without touching every view.
"""
from __future__ import annotations

ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
ACCENT_PRESS = "#1e40af"
ACCENT_SOFT = "#e8f0fe"
_BORDER = "#e0e0e0"
_MUTED = "#6b7280"

_CHROME = f"""
/* ---------- Sidebar (custom nav rail) ---------- */
#Sidebar {{ background: #f7f7f7; border-right: 1px solid {_BORDER}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 8px 12px; margin: 1px 6px;
    border: none; border-radius: 6px; background: transparent;
    color: #1f1f1f; font-size: 13px; font-weight: 500;
}}
#Sidebar QPushButton:hover {{ background: #ececec; }}
#Sidebar QPushButton:checked {{
    background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600;
}}
#Sidebar QPushButton#Secondary {{ background: transparent; color: {_MUTED}; border: none; }}
#Sidebar QPushButton#Secondary:hover {{ background: #ececec; color: #1f1f1f; }}
#BrandName {{ font-size: 15px; font-weight: 600; color: #1f1f1f; }}
#BrandSub  {{ font-size: 11px; color: {_MUTED}; }}
#BrandLogo {{ background: {ACCENT_SOFT}; border-radius: 8px; }}

/* ---------- Top header bar (custom) ---------- */
#HeaderBar {{ background: #ffffff; border-bottom: 1px solid {_BORDER}; }}
#HeaderTitle {{ font-size: 18px; font-weight: 600; color: #1f1f1f; }}
#HeaderSub {{ font-size: 12px; color: {_MUTED}; }}
#UserName {{ font-size: 13px; font-weight: 600; color: #1f1f1f; }}
#UserRole {{ font-size: 11px; color: {_MUTED}; }}
#Avatar {{
    background: {ACCENT_SOFT}; color: {ACCENT}; border-radius: 17px;
    font-size: 13px; font-weight: 700;
}}

/* ---------- Page-level labels & cards ---------- */
QLabel#PageTitle {{ font-size: 20px; font-weight: 700; color: #1f1f1f; }}
QLabel#Muted {{ color: {_MUTED}; }}
#Card {{ background: #ffffff; border: 1px solid {_BORDER}; border-radius: 8px; }}

/* ---------- Buttons: primary (accent) vs secondary (outline) ---------- */
QPushButton {{
    background: {ACCENT}; color: #ffffff; border: none; border-radius: 6px;
    padding: 7px 16px; font-weight: 600; min-height: 16px;
}}
QPushButton:hover {{ background: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background: {ACCENT_PRESS}; }}
QPushButton:disabled {{ background: #c9ced6; color: #f2f4f7; }}
QPushButton#Secondary {{
    background: #ffffff; color: #1f1f1f; border: 1px solid #cfd3d9; font-weight: 500;
}}
QPushButton#Secondary:hover {{ background: #f0f2f5; border-color: #b3b9c2; }}
QPushButton#Secondary:pressed {{ background: #e6e9ee; }}
QPushButton#Secondary:disabled {{ background: #f5f6f8; color: #b8bcc4; border-color: #e3e6ea; }}
QPushButton#Danger {{ background: #b91c1c; color: #ffffff; }}
QPushButton#Danger:hover {{ background: #991b1b; }}
QPushButton#Danger:pressed {{ background: #7f1616; }}
/* success (green confirm) */
QPushButton#Success {{ background: #16a34a; color: #ffffff; }}
QPushButton#Success:hover {{ background: #15803d; }}
QPushButton#Success:pressed {{ background: #166534; }}
QPushButton#Success:disabled {{ background: #c9ced6; color: #f2f4f7; }}
/* success OUTLINE (green text, green border, light fill) */
QPushButton#SuccessOutline {{
    background: #ffffff; color: #16a34a; border: 1px solid #16a34a; font-weight: 600;
}}
QPushButton#SuccessOutline:hover {{ background: #f0fdf4; }}
QPushButton#SuccessOutline:pressed {{ background: #dcfce7; }}
/* selectable payment chip */
QPushButton#Chip {{
    background: #ffffff; color: #1f1f1f; border: 1px solid #cfd3d9;
    border-radius: 14px; padding: 5px 12px; font-weight: 500;
}}
QPushButton#Chip:hover {{ background: #f0f2f5; }}
QPushButton#Chip:checked {{
    background: {ACCENT_SOFT}; color: {ACCENT}; border-color: {ACCENT}; font-weight: 600;
}}
/* small qty +/- stepper buttons (no global padding so the glyph shows) */
QPushButton#StepBtn {{
    background: #f3f4f6; color: #111827; border: 1px solid #cfd3d9;
    border-radius: 6px; font-size: 16px; font-weight: 700; padding: 0;
}}
QPushButton#StepBtn:hover {{ background: #e5e7eb; }}
QPushButton#StepBtn:pressed {{ background: #d1d5db; }}
QPushButton#StepBtn:disabled {{ color: #b8bcc4; background: #f6f7f9; }}
/* soft red remove button with a visible x */
QPushButton#RemoveBtn {{
    background: #fdecec; color: #dc2626; border: 1px solid #f3b4b4;
    border-radius: 6px; font-size: 15px; font-weight: 700; padding: 0;
}}
QPushButton#RemoveBtn:hover {{ background: #fbdada; }}
QPushButton#RemoveBtn:pressed {{ background: #f7c5c5; }}

/* ---------- Dialogs: one consistent, modern look everywhere ---------- */
/* Scoped to QDialog so the main screens/tables are untouched. */
QDialog {{ background: #ffffff; }}
QDialog QLineEdit, QDialog QComboBox, QDialog QSpinBox, QDialog QDoubleSpinBox,
QDialog QDateEdit, QDialog QPlainTextEdit, QDialog QTextEdit {{
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 4px 10px; min-height: 30px; color: #0f172a;
    selection-background-color: {ACCENT_SOFT}; selection-color: #0f172a;
}}
QDialog QLineEdit:focus, QDialog QComboBox:focus, QDialog QSpinBox:focus,
QDialog QDoubleSpinBox:focus, QDialog QDateEdit:focus,
QDialog QPlainTextEdit:focus, QDialog QTextEdit:focus {{
    border: 1px solid {ACCENT}; background: #ffffff;
}}
QDialog QComboBox::drop-down {{ border: none; width: 22px; }}
/* Spin boxes: styling a spinner hides its native arrows, so re-draw the +/-
   buttons (with CSS-triangle arrows) or they vanish. */
QDialog QSpinBox, QDialog QDoubleSpinBox {{ padding-right: 20px; }}
QDialog QSpinBox::up-button, QDialog QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 18px;
    border-left: 1px solid #e2e8f0; border-top-right-radius: 8px; background: #eef2f7;
}}
QDialog QSpinBox::down-button, QDialog QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 18px;
    border-left: 1px solid #e2e8f0; border-bottom-right-radius: 8px; background: #eef2f7;
}}
QDialog QSpinBox::up-button:hover, QDialog QDoubleSpinBox::up-button:hover,
QDialog QSpinBox::down-button:hover, QDialog QDoubleSpinBox::down-button:hover {{
    background: #e2e8f0;
}}
QDialog QSpinBox::up-arrow, QDialog QDoubleSpinBox::up-arrow {{
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid #475569;
}}
QDialog QSpinBox::down-arrow, QDialog QDoubleSpinBox::down-arrow {{
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #475569;
}}
QDialog QLabel {{ color: #334155; }}
/* dialog action buttons: consistent sizing */
QDialog QPushButton {{ min-height: 32px; padding: 4px 16px; }}
QDialog QDialogButtonBox QPushButton {{ min-width: 84px; }}
"""


def apply_theme(app) -> None:
    """Force the Fusion style, then apply the app chrome + button styling.

    We deliberately do NOT use the native Windows style. The native styles differ
    per OS version (Windows 11 vs the older Vista style on many shop laptops),
    which drew tables/controls differently machine-to-machine (beveled, boxy
    cells). Fusion is Qt-drawn and looks IDENTICAL on every PC and at every screen
    size / DPI, so the shop sees the same structure everywhere."""
    try:
        from PySide6.QtWidgets import QStyleFactory
        if "Fusion" in set(QStyleFactory.keys()):
            app.setStyle("Fusion")
    except Exception:
        pass
    app.setStyleSheet(_CHROME)
