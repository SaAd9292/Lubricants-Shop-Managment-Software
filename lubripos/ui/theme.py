"""Penguix styling — a token-driven light/dark theme.

One set of design tokens per mode (colours only) feeds a single stylesheet
builder, so light and dark stay perfectly in sync and there are no scattered
hex values. The custom chrome (sidebar, header, cards, buttons, inputs, tables)
is styled via the stylesheet; the generic Qt widgets (menus, tooltips, combo
popups, scrollbars, plain backgrounds) follow the QPalette we set — which is why
dark mode needs both a stylesheet AND a dark palette.

Button hierarchy is unchanged: primary buttons get the accent fill (one clear
call-to-action per screen); buttons tagged objectName "Secondary" are quiet
outlined buttons; "Danger"/"Success" carry semantic colour.
"""
from __future__ import annotations

# ---- design tokens -------------------------------------------------------
LIGHT = {
    "accent": "#2563eb", "accent_hover": "#1d4ed8", "accent_press": "#1e40af",
    "accent_soft": "#e8f0fe", "on_soft": "#2563eb",
    "ink": "#1f1f1f", "muted": "#6b7280", "border": "#e0e0e0",
    "sidebar_bg": "#f7f7f7", "sidebar_text": "#1f1f1f", "sidebar_hover": "#ececec",
    "header_bg": "#ffffff",
    "card_bg": "#ffffff", "card_border": "#e0e0e0",
    "input_bg": "#f8fafc", "input_border": "#e2e8f0", "input_text": "#0f172a",
    "input_focus_bg": "#ffffff", "input_dis_bg": "#f1f3f6", "input_dis_text": "#9aa3af",
    "spin_bg": "#eef2f7", "spin_arrow": "#475569", "spin_border": "#e2e8f0",
    "thead_bg": "#f8fafc", "thead_text": "#475569", "thead_border": "#e2e8f0",
    "grid": "#eef2f7", "table_border": "#edf0f3", "table_alt": "#fbfcfe",
    "sec_bg": "#ffffff", "sec_text": "#1f1f1f", "sec_border": "#cfd3d9",
    "sec_hover": "#f0f2f5", "sec_press": "#e6e9ee",
    "sec_dis_bg": "#f5f6f8", "sec_dis_text": "#b8bcc4", "sec_dis_border": "#e3e6ea",
    "btn_dis_bg": "#c9ced6", "btn_dis_text": "#f2f4f7",
    "chip_hover": "#f0f2f5",
    "step_bg": "#f3f4f6", "step_text": "#111827", "step_border": "#cfd3d9",
    "step_hover": "#e5e7eb", "step_press": "#d1d5db",
    "step_dis_bg": "#f6f7f9", "step_dis_text": "#b8bcc4",
    "dialog_bg": "#ffffff", "dialog_label": "#334155",
}

DARK = {
    "accent": "#3b82f6", "accent_hover": "#2563eb", "accent_press": "#1d4ed8",
    "accent_soft": "#1e2a44", "on_soft": "#93c5fd",
    "ink": "#e2e8f0", "muted": "#94a3b8", "border": "#334155",
    "sidebar_bg": "#0f172a", "sidebar_text": "#e2e8f0", "sidebar_hover": "#1e293b",
    "header_bg": "#111827",
    "card_bg": "#1e293b", "card_border": "#334155",
    "input_bg": "#1e293b", "input_border": "#334155", "input_text": "#e2e8f0",
    "input_focus_bg": "#243149", "input_dis_bg": "#1a2231", "input_dis_text": "#5b6472",
    "spin_bg": "#243149", "spin_arrow": "#94a3b8", "spin_border": "#334155",
    "thead_bg": "#172033", "thead_text": "#94a3b8", "thead_border": "#334155",
    "grid": "#26334a", "table_border": "#2a3852", "table_alt": "#1b2740",
    "sec_bg": "#1e293b", "sec_text": "#e2e8f0", "sec_border": "#3b4a61",
    "sec_hover": "#273549", "sec_press": "#2f3f57",
    "sec_dis_bg": "#1a2231", "sec_dis_text": "#5b6472", "sec_dis_border": "#2a3852",
    "btn_dis_bg": "#334155", "btn_dis_text": "#64748b",
    "chip_hover": "#273549",
    "step_bg": "#243149", "step_text": "#e2e8f0", "step_border": "#3b4a61",
    "step_hover": "#2b3a52", "step_press": "#324564",
    "step_dis_bg": "#1a2231", "step_dis_text": "#5b6472",
    "dialog_bg": "#111827", "dialog_label": "#cbd5e1",
}

# semantic colours that read well on BOTH themes (kept out of the token maps)
_DANGER, _DANGER_H, _DANGER_P = "#b91c1c", "#991b1b", "#7f1616"
_SUCCESS, _SUCCESS_H, _SUCCESS_P = "#16a34a", "#15803d", "#166534"


def _stylesheet(t: dict) -> str:
    return f"""
/* ---------- Sidebar (custom nav rail) ---------- */
#Sidebar {{ background: {t['sidebar_bg']}; border-right: 1px solid {t['border']}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 8px 12px; margin: 1px 6px;
    border: none; border-radius: 6px; background: transparent;
    color: {t['sidebar_text']}; font-size: 13px; font-weight: 500;
}}
#Sidebar QPushButton:hover {{ background: {t['sidebar_hover']}; }}
#Sidebar QPushButton:checked {{
    background: {t['accent_soft']}; color: {t['on_soft']}; font-weight: 600;
}}
#Sidebar QPushButton#Secondary {{ background: transparent; color: {t['muted']}; border: none; }}
#Sidebar QPushButton#Secondary:hover {{ background: {t['sidebar_hover']}; color: {t['sidebar_text']}; }}
#BrandName {{ font-size: 15px; font-weight: 600; color: {t['sidebar_text']}; }}
#BrandSub  {{ font-size: 11px; color: {t['muted']}; }}
#BrandLogo {{ background: {t['accent_soft']}; border-radius: 8px; }}

/* ---------- Top header bar (custom) ---------- */
#HeaderBar {{ background: {t['header_bg']}; border-bottom: 1px solid {t['border']}; }}
#HeaderTitle {{ font-size: 18px; font-weight: 600; color: {t['ink']}; }}
#HeaderSub {{ font-size: 12px; color: {t['muted']}; }}
#UserName {{ font-size: 13px; font-weight: 600; color: {t['ink']}; }}
#UserRole {{ font-size: 11px; color: {t['muted']}; }}
#Avatar {{
    background: {t['accent_soft']}; color: {t['on_soft']}; border-radius: 17px;
    font-size: 13px; font-weight: 700;
}}

/* ---------- Page-level labels & cards ---------- */
QLabel#PageTitle {{ font-size: 20px; font-weight: 700; color: {t['ink']}; }}
QLabel#Muted {{ color: {t['muted']}; }}
#Card {{ background: {t['card_bg']}; border: 1px solid {t['card_border']}; border-radius: 8px; }}

/* ---------- Buttons: primary (accent) vs secondary (outline) ---------- */
QPushButton {{
    background: {t['accent']}; color: #ffffff; border: none; border-radius: 6px;
    padding: 7px 16px; font-weight: 600; min-height: 16px;
}}
QPushButton:hover {{ background: {t['accent_hover']}; }}
QPushButton:pressed {{ background: {t['accent_press']}; }}
QPushButton:disabled {{ background: {t['btn_dis_bg']}; color: {t['btn_dis_text']}; }}
QPushButton#Secondary {{
    background: {t['sec_bg']}; color: {t['sec_text']}; border: 1px solid {t['sec_border']}; font-weight: 500;
}}
QPushButton#Secondary:hover {{ background: {t['sec_hover']}; border-color: {t['accent']}; }}
QPushButton#Secondary:pressed {{ background: {t['sec_press']}; }}
QPushButton#Secondary:disabled {{ background: {t['sec_dis_bg']}; color: {t['sec_dis_text']}; border-color: {t['sec_dis_border']}; }}
QPushButton#Danger {{ background: {_DANGER}; color: #ffffff; }}
QPushButton#Danger:hover {{ background: {_DANGER_H}; }}
QPushButton#Danger:pressed {{ background: {_DANGER_P}; }}
QPushButton#Success {{ background: {_SUCCESS}; color: #ffffff; }}
QPushButton#Success:hover {{ background: {_SUCCESS_H}; }}
QPushButton#Success:pressed {{ background: {_SUCCESS_P}; }}
QPushButton#Success:disabled {{ background: {t['btn_dis_bg']}; color: {t['btn_dis_text']}; }}
QPushButton#SuccessOutline {{
    background: {t['sec_bg']}; color: {_SUCCESS}; border: 1px solid {_SUCCESS}; font-weight: 600;
}}
QPushButton#SuccessOutline:hover {{ background: {t['sec_hover']}; }}
QPushButton#SuccessOutline:pressed {{ background: {t['sec_press']}; }}
QPushButton#Chip {{
    background: {t['sec_bg']}; color: {t['sec_text']}; border: 1px solid {t['sec_border']};
    border-radius: 14px; padding: 5px 12px; font-weight: 500;
}}
QPushButton#Chip:hover {{ background: {t['chip_hover']}; }}
QPushButton#Chip:checked {{
    background: {t['accent_soft']}; color: {t['on_soft']}; border-color: {t['accent']}; font-weight: 600;
}}
QPushButton#StepBtn {{
    background: {t['step_bg']}; color: {t['step_text']}; border: 1px solid {t['step_border']};
    border-radius: 6px; font-size: 16px; font-weight: 700; padding: 0;
}}
QPushButton#StepBtn:hover {{ background: {t['step_hover']}; }}
QPushButton#StepBtn:pressed {{ background: {t['step_press']}; }}
QPushButton#StepBtn:disabled {{ color: {t['step_dis_text']}; background: {t['step_dis_bg']}; }}
QPushButton#RemoveBtn {{
    background: #fdecec; color: #dc2626; border: 1px solid #f3b4b4;
    border-radius: 6px; font-size: 15px; font-weight: 700; padding: 0;
}}
QPushButton#RemoveBtn:hover {{ background: #fbdada; }}
QPushButton#RemoveBtn:pressed {{ background: #f7c5c5; }}

/* ---------- Form controls: one consistent look EVERYWHERE ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {t['input_bg']}; border: 1px solid {t['input_border']}; border-radius: 8px;
    padding: 4px 10px; min-height: 30px; color: {t['input_text']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {t['accent']}; background: {t['input_focus_bg']};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateEdit:disabled {{
    background: {t['input_dis_bg']}; color: {t['input_dis_text']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t['input_focus_bg']}; color: {t['input_text']};
    border: 1px solid {t['input_border']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']};
}}
QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 18px;
    border-left: 1px solid {t['spin_border']}; border-top-right-radius: 8px; background: {t['spin_bg']};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 18px;
    border-left: 1px solid {t['spin_border']}; border-bottom-right-radius: 8px; background: {t['spin_bg']};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t['spin_border']};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid {t['spin_arrow']};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {t['spin_arrow']};
}}

/* ---------- Tables: modern, quiet, consistent ---------- */
QHeaderView::section {{
    background: {t['thead_bg']}; color: {t['thead_text']}; border: none;
    border-bottom: 1px solid {t['thead_border']}; padding: 7px 8px; font-weight: 600;
}}
QTableWidget, QTableView {{
    background: {t['card_bg']}; color: {t['ink']};
    gridline-color: {t['grid']}; border: 1px solid {t['table_border']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']};
    alternate-background-color: {t['table_alt']};
}}
QTableView::item {{ padding: 3px 4px; }}
QTableView::item:selected {{ color: {t['ink']}; }}
QTableCornerButton::section {{ background: {t['thead_bg']}; border: none; }}

/* ---------- Dialogs ---------- */
QDialog {{ background: {t['dialog_bg']}; }}
QDialog QLabel {{ color: {t['dialog_label']}; }}
QDialog QPushButton {{ min-height: 32px; padding: 4px 16px; }}
QDialog QDialogButtonBox QPushButton {{ min-width: 84px; }}
"""


def resolve_mode(value) -> str:
    """Normalise a stored preference (or None) to 'light' | 'dark'."""
    return "dark" if str(value or "").strip().lower() in ("dark", "1", "true") else "light"


def _dark_palette():
    """A Fusion-compatible dark palette so the non-stylesheet bits (menus,
    tooltips, scrollbars, plain page backgrounds, disabled text) go dark too."""
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    window = QColor("#0f172a")
    base = QColor("#111827")
    text = QColor("#e2e8f0")
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, QColor("#1b2740"))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor("#1e293b"))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.ToolTipBase, QColor("#1e293b"))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.PlaceholderText, QColor("#64748b"))
    p.setColor(QPalette.Highlight, QColor("#2563eb"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Link, QColor("#60a5fa"))
    for grp in (QPalette.Disabled,):
        p.setColor(grp, QPalette.Text, QColor("#5b6472"))
        p.setColor(grp, QPalette.WindowText, QColor("#5b6472"))
        p.setColor(grp, QPalette.ButtonText, QColor("#5b6472"))
    return p


def apply_theme(app, mode: str = "light") -> None:
    """Force Fusion (identical rendering on every Windows version/DPI), then
    apply the palette + stylesheet for the chosen mode.

    mode: 'light' (default) or 'dark'. Call again at runtime to switch live."""
    mode = resolve_mode(mode)
    try:
        from PySide6.QtWidgets import QStyleFactory
        if "Fusion" in set(QStyleFactory.keys()):
            app.setStyle("Fusion")
    except Exception:
        pass
    try:
        if mode == "dark":
            app.setPalette(_dark_palette())
        else:
            app.setPalette(app.style().standardPalette())
    except Exception:
        pass
    app.setStyleSheet(_stylesheet(DARK if mode == "dark" else LIGHT))
