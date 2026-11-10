"""Sistema visual propio (spec temas Gipler).

Dos paletas con selector en la aplicación. Sin dependencia del tema
del escritorio. QSettings recuerda el tema (org/app de la app).
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

ORG = "Gipler"
APP = "Gipler"

PALETTES: dict[str, dict[str, str]] = {
    "oscuro": {
        "fondo": "#20252D", "panel": "#292F39", "panel2": "#323A46",
        "tabla": "#252B34", "texto": "#E5EAF0", "texto2": "#A6B0BE",
        "borde": "#414B59", "seleccion": "#344F70", "acento": "#6BA6E8",
    },
    "claro": {
        "fondo": "#E9EDF2", "panel": "#FFFFFF", "panel2": "#F3F5F8",
        "tabla": "#FFFFFF", "texto": "#202B38", "texto2": "#657386",
        "borde": "#D2D9E2", "seleccion": "#DCEBFA", "acento": "#2767A5",
    },
}

# Colores semánticos adaptados por tema (mismos estados del motor).
SEMANTIC: dict[str, dict[str, str]] = {
    "oscuro": {
        "new_in_dev": "#7ED68B", "modified_in_dev": "#6BA6E8",
        "identical": "#A6B0BE", "missing_in_dev": "#7C8594",
        "ambiguous": "#F2A24B",
    },
    "claro": {
        "new_in_dev": "#1E7B3C", "modified_in_dev": "#2767A5",
        "identical": "#657386", "missing_in_dev": "#8A99AD",
        "ambiguous": "#B45309",
    },
}

DEFAULT_THEME = "oscuro"


def load_preference() -> str:
    from gipler.config import get_settings

    s = get_settings()
    theme = s.value("tema", DEFAULT_THEME)
    return theme if theme in PALETTES else DEFAULT_THEME


def save_preference(theme: str) -> None:
    from gipler.config import get_settings

    get_settings().setValue("tema", theme)


def palette(theme: str) -> QPalette:
    cols = PALETTES.get(theme, PALETTES[DEFAULT_THEME])
    p = QPalette()
    p.setColor(QPalette.Window, QColor(cols["fondo"]))
    p.setColor(QPalette.WindowText, QColor(cols["texto"]))
    p.setColor(QPalette.Base, QColor(cols["tabla"]))
    p.setColor(QPalette.AlternateBase, QColor(cols["panel"]))
    p.setColor(QPalette.Text, QColor(cols["texto"]))
    p.setColor(QPalette.Button, QColor(cols["panel"]))
    p.setColor(QPalette.ButtonText, QColor(cols["texto"]))
    p.setColor(QPalette.Highlight, QColor(cols["seleccion"]))
    p.setColor(QPalette.HighlightedText, QColor(cols["texto"]))
    p.setColor(QPalette.Link, QColor(cols["acento"]))
    p.setColor(QPalette.Midlight, QColor(cols["borde"]))
    p.setColor(QPalette.Mid, QColor(cols["borde"]))
    p.setColor(QPalette.Dark, QColor(cols["texto2"]))
    p.setColor(QPalette.Light, QColor(cols["panel2"]))
    p.setColor(QPalette.PlaceholderText, QColor(cols["texto2"]))
    p.setColor(QPalette.ToolTipBase, QColor(cols["panel"]))
    p.setColor(QPalette.ToolTipText, QColor(cols["texto"]))
    return p


def stylesheet(theme: str) -> str:
    c = PALETTES.get(theme, PALETTES[DEFAULT_THEME])
    return f"""
QToolBar {{ background: {c['panel']}; border: 1px solid {c['borde']}; }}
QPushButton, QToolButton {{ background: {c['panel']}; color: {c['texto']};
    border: 1px solid {c['borde']}; padding: 4px 8px; }}
QPushButton:checked {{ background: {c['seleccion']}; }}
QComboBox, QLineEdit {{ background: {c['tabla']}; color: {c['texto']};
    border: 1px solid {c['borde']}; padding: 3px 4px; }}
QTreeView {{ background: {c['tabla']}; color: {c['texto']};
    alternate-background-color: {c['panel2']}; selection-background-color: {c['seleccion']}; }}
QTabWidget::pane {{ background: {c['tabla']}; border: 1px solid {c['borde']}; }}
QTabBar::tab {{ background: {c['panel']}; color: {c['texto2']}; padding: 6px 12px;
    border: 1px solid {c['borde']}; }}
QTabBar::tab:selected {{ color: {c['texto']}; background: {c['panel2']}; }}
QPlainTextEdit, QTableWidget {{ background: {c['tabla']}; color: {c['texto']}; }}
QStatusBar {{ background: {c['panel']}; color: {c['texto2']}; }}
QScrollBar:vertical {{ background: {c['panel']}; width: 12px; }}
QScrollBar::handle:vertical {{ background: {c['borde']}; min-height: 24px; }}
QScrollBar:horizontal {{ background: {c['panel']}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {c['borde']}; min-width: 24px; }}
QHeaderView::section {{ background: {c['panel2']}; color: {c['texto']};
    padding: 3px; border: 1px solid {c['borde']}; }}
QDialog {{ background: {c['fondo']}; }}
QLabel {{ color: {c['texto']}; }}
"""


def apply_theme(theme: str) -> None:
    app = QApplication.instance()
    if app is not None:
        app.setPalette(palette(theme))
        app.setStyleSheet(stylesheet(theme))
    save_preference(theme)


def semantic(theme: str, key: str) -> str:
    return SEMANTIC.get(theme, SEMANTIC[DEFAULT_THEME]).get(key, "")
