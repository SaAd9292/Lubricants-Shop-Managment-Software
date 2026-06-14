"""Light theme via Qt Style Sheets (QSS).

A single accent plus a neutral surface palette keeps every screen consistent.
Penguix ships light-only; call apply_theme(app) to apply it.
"""
from __future__ import annotations

ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"

_BASE = """
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 14px;
}}
QWidget {{ color: {fg}; background: transparent; }}
QMainWindow, QDialog {{ background: {bg}; }}

/* ---------- Sidebar ---------- */
#Sidebar {{ background: {sidebar_bg}; border-right: 1px solid {border}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 11px 16px; margin: 1px 0;
    border: none; border-radius: 10px;
    color: {sidebar_fg}; background: transparent; font-size: 14px; font-weight: 500;
}}
#Sidebar QPushButton:hover {{ background: {accent_soft}; color: {fg}; }}
#Sidebar QPushButton:checked {{
    background: {accent}; color: #ffffff; font-weight: 700;
}}
#BrandLabel {{
    font-size: 19px; font-weight: 800; padding: 14px 14px 18px 14px; color: {fg};
}}

/* ---------- Cards / group boxes ---------- */
#Card {{
    background: {surface}; border: 1px solid {border}; border-radius: 14px;
}}
QGroupBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 14px;
    margin-top: 16px; padding: 18px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 14px; padding: 2px 6px;
    color: {muted}; font-weight: 700;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {border}; }}

/* ---------- Inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QDateEdit {{
    background: {input_bg}; border: 1px solid {border}; border-radius: 9px;
    padding: 8px 11px; min-height: 20px;
    selection-background-color: {accent}; selection-color: #fff;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover {{
    border: 1px solid {border_strong};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus {{
    border: 1px solid {accent};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border};
    selection-background-color: {accent}; selection-color: #fff; outline: none;
    border-radius: 8px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 18px; border: none; }}

/* ---------- Buttons ---------- */
QPushButton {{
    background: {accent}; color: #fff; border: none; border-radius: 9px;
    padding: 9px 18px; font-weight: 600; min-height: 18px;
}}
QPushButton:hover {{ background: {accent_hover}; }}
QPushButton:pressed {{ background: {accent_press}; }}
QPushButton:disabled {{ background: {border}; color: {muted}; }}
QPushButton#Secondary {{
    background: {surface}; color: {fg}; border: 1px solid {border_strong};
}}
QPushButton#Secondary:hover {{ background: {accent_soft}; border-color: {accent}; }}
QPushButton#Secondary:pressed {{ background: {border}; }}

/* ---------- Tables ---------- */
QTableView, QTableWidget {{
    background: {surface}; border: 1px solid {border}; border-radius: 12px;
    gridline-color: {grid};
    selection-background-color: {accent}; selection-color: #fff;
}}
QTableView::item, QTableWidget::item {{ padding: 6px 8px; }}
QTableView::item:selected, QTableWidget::item:selected {{ color: #fff; }}
QHeaderView::section {{
    background: {table_header}; color: {muted}; padding: 10px 8px;
    border: none; border-bottom: 1px solid {border}; font-weight: 700;
}}
QHeaderView::section:hover {{ color: {fg}; }}
QTableCornerButton::section {{ background: {table_header}; border: none; }}
QTableView:focus, QTableWidget:focus {{ border: 1px solid {accent}; }}
QTableView::item:hover, QTableWidget::item:hover {{ background: {accent_soft}; }}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {scroll}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {scroll}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {scroll_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- Checkboxes ---------- */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {border_strong};
    border-radius: 5px; background: {input_bg};
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

/* ---------- Misc ---------- */
QLabel#PageTitle {{ font-size: 24px; font-weight: 800; }}
QLabel#Muted {{ color: {muted}; }}
QStatusBar {{ background: {sidebar_bg}; color: {muted}; border-top: 1px solid {border}; }}
QToolTip {{
    background: {fg}; color: {bg}; border: none; padding: 6px 8px; border-radius: 6px;
}}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent}; color: #fff; }}
"""

_LIGHT = dict(
    bg="#f4f6fb", fg="#0f172a", muted="#64748b",
    surface="#ffffff", sidebar_bg="#ffffff", sidebar_fg="#475569",
    input_bg="#ffffff", border="#e6e9f0", border_strong="#cbd5e1",
    grid="#eef1f6", table_header="#f8fafc",
    accent=ACCENT, accent_hover=ACCENT_HOVER, accent_press="#1e40af",
    accent_soft="#eef2ff", scroll="#cbd5e1", scroll_hover="#94a3b8",
)


def stylesheet() -> str:
    return _BASE.format(**_LIGHT)


def apply_theme(app) -> None:
    app.setStyleSheet(stylesheet())
