# theme.py
from __future__ import annotations

def _hex(h: str) -> str:
    h = h.strip().lower().replace("#", "")
    if len(h) == 3:
        h = "".join(c*2 for c in h)
    return f"#{h}"

def _rgba(h: str, a: float) -> str:
    h = _hex(h)[1:]
    r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"

def apply_theme(app, accent: str="#ff3030"):
    ACCENT    = _hex(accent)
    ACCENT_10 = _rgba(accent, 0.10)
    ACCENT_16 = _rgba(accent, 0.16)
    ACCENT_22 = _rgba(accent, 0.22)

    style = f"""
    /* ====== Global ====== */
    * {{
        font-family: 'Segoe UI', 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
        color: #101114;
        font-size: 13.5px;
    }}
    QWidget {{
        background: #f7f8fa;
    }}
    QFrame#Card, QTextEdit#Card, QTableWidget#Card {{
        background: #ffffff;
        border: 1px solid #e6e8eb;
        border-radius: 14px;
    }}

    /* ====== Tabs ====== */
    QTabWidget::pane {{
        border: none;
        margin: 12px 12px 0 12px;
    }}
    QTabBar::tab {{
        background: transparent;
        margin-right: 8px;
        padding: 10px 16px;
        border-radius: 12px;
        color: #6b7280;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: #ffffff;
        color: #101114;
        border: 1px solid #e6e8eb;
    }}

    /* ====== Inputs ====== */
    QLineEdit, QComboBox {{
        background: #ffffff;
        border: 1px solid #d9dde3;
        border-radius: 12px;
        padding: 9px 12px;
        selection-background-color: {ACCENT_22};
    }}
    QLineEdit:focus, QComboBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        width: 28px;
        border-top-right-radius: 12px;
        border-bottom-right-radius: 12px;
        border-left: 1px solid #e6e8eb;
        background: #fafbfc;
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0; height: 0;
        border-left: 6px solid transparent;
        border-right: 6px solid transparent;
        border-top: 7px solid #6b7280;
        margin-right: 10px;
    }}

    /* ====== Buttons ====== */
    QPushButton {{
        border: 1px solid #e6e8eb;
        border-radius: 12px;
        padding: 8px 14px;
        background: #ffffff;
    }}
    QPushButton[type="primary"] {{
        background: {ACCENT};
        border-color: {ACCENT};
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton[type="primary"]:hover {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QPushButton[type="outline"] {{
        color: {ACCENT};
        background: transparent;
        border-color: {ACCENT};
        font-weight: 600;
    }}
    QPushButton[type="ghost"] {{
        background: transparent;
        border-color: transparent;
        color: #374151;
    }}
    QPushButton:disabled {{
        opacity: .45;
    }}

    /* ====== CheckBox ====== */
    QCheckBox {{
        spacing: 8px;
        font-weight: 500;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid #d1d5db;
        background: #ffffff;
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        image: none;
    }}
    QCheckBox::indicator:unchecked {{
        background: #ffffff;
        image: none;
    }}

    /* ====== Table ====== */
    QTableWidget {{
        background: #ffffff;
        border: 1px solid #e6e8eb;
        border-radius: 14px;
        gridline-color: #eef1f4;
        alternate-background-color: #fbfcfe;
        selection-background-color: {ACCENT_10};
        selection-color: #101114;
    }}
    QHeaderView::section {{
        background: #fafbfc;
        color: #374151;
        font-weight: 600;
        padding: 9px 10px;
        border: none;
        border-bottom: 1px solid #e6e8eb;
    }}
    QHeaderView::section:hover {{
        background: #ffffff;
    }}
    QHeaderView::section:pressed {{
        color: {ACCENT};
    }}
    QTableCornerButton::section {{
        background: #fafbfc;
        border: none;
        border-bottom: 1px solid #e6e8eb;
    }}

    /* ====== Scrollbar ====== */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 8px 2px 8px 0;
    }}
    QScrollBar::handle:vertical {{
        background: #cfd5dd;
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: transparent;
    }}
    """
    app.setStyleSheet(style)
