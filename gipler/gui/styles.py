"""Sistema visual común de Gipler.

Define la paleta, los radios, el espaciado y los estilos compartidos por
Inicio, referencias, Excluidos e Indeterminados. Se aplica globalmente para
evitar QSS duplicado en cada pestaña.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from gipler.gui.theme import PALETTES, load_preference

RADIUS_PANEL = 10
RADIUS_CONTROL = 6
RADIUS_MENU = 8
PADDING_PANEL = 12
PADDING_SECTION = 12
SPACING_SECTION = 10
CONTROL_HEIGHT = 32


def palette(theme: str | None = None) -> dict[str, str]:
    current = theme or load_preference()
    return PALETTES.get(current, PALETTES["oscuro"])


def make_context_label(text: str = "") -> QLabel:
    """Información contextual compartida por Sincronización y Git.

    Es el mismo componente visual en ambas vistas: mismo objeto, estilo,
    tipografía, alineación, padding y posición relativa a sus controles.
    """
    label = QLabel(text)
    label.setObjectName("contextLabel")
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    label.setMinimumWidth(155)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + 0.5)
    label.setFont(font)
    label.setAccessibleName("Información contextual")
    return label


def common_stylesheet(theme: str | None = None) -> str:
    p = palette(theme)
    return f"""
QWidget#panelSurface {{ background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: {RADIUS_PANEL}px; }}
QLabel {{ color: {p['texto']}; }}
QLabel#sectionTitle {{ color: {p['texto']}; font-size: 13px; font-weight: 700; }}
QLabel#contextLabel {{ color: {p['texto2']}; font-size: 11px; padding: 4px 8px; }}
QLabel#emptyState {{ color: {p['texto2']}; font-size: 12px; background: transparent; }}
QComboBox {{
    background: {p['tabla']}; color: {p['texto']}; border: 1px solid {p['borde']};
    border-radius: {RADIUS_CONTROL}px; padding: 6px 8px; min-height: {CONTROL_HEIGHT - 12}px;
}}
QComboBox:hover {{ border-color: {p['acento']}; }}
QComboBox:focus {{ border-color: {p['acento']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: {RADIUS_CONTROL}px;
    selection-background-color: {p['seleccion']}; selection-color: {p['texto']};
}}
QLineEdit {{
    background: {p['tabla']}; color: {p['texto']}; border: 1px solid {p['borde']};
    border-radius: {RADIUS_CONTROL}px; padding: 6px 8px; min-height: {CONTROL_HEIGHT - 12}px;
}}
QLineEdit:focus {{ border-color: {p['acento']}; }}
QPushButton {{
    background: {p['panel2']}; color: {p['texto']}; border: 1px solid {p['borde']};
    border-radius: {RADIUS_CONTROL}px; padding: 7px 12px;
}}
QPushButton:hover {{ border-color: {p['acento']}; }}
QPushButton:disabled {{ background: {p['panel2']}; color: {p['texto2']}; border-color: {p['borde']}; }}
QToolButton {{
    background: transparent; color: {p['texto']}; border: 1px solid {p['borde']};
    border-radius: {RADIUS_CONTROL}px; padding: 4px 8px;
}}
QToolButton:hover {{ border-color: {p['acento']}; }}
QPushButton#assignPlusButton {{
    background: transparent; border: none; color: {p['texto2']}; font-size: 14px;
    font-weight: 600; padding: 0px; min-width: 22px; min-height: 22px;
}}
QPushButton#assignPlusButton:hover {{
    color: {p['acento']}; background: rgba(127, 127, 127, 0.10); border-radius: 4px;
}}
QMenu {{
    background: {p['panel']}; border: 1px solid {p['borde']}; border-radius: {RADIUS_MENU}px;
    padding: 4px;
}}
QMenu::item {{ color: {p['texto']}; padding: 6px 18px 6px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {p['seleccion']}; color: {p['texto']}; }}
QMenu::item:disabled {{ color: {p['texto2']}; }}
QMenu::separator {{ height: 1px; background: {p['borde']}; margin: 4px 6px; }}
QFrame#directoryHeader {{
    background: {p['panel2']}; border: none; border-radius: 0px;
}}
QLabel#directoryHeaderTitle {{
    background: transparent; border: none; color: {p['texto']};
}}
QTreeView {{ background: transparent; border: none; outline: none; }}
QTreeView::item {{ background: transparent; }}
QTreeView::item:selected {{ background: {p['seleccion']}; }}
QTreeView::item:hover {{ background: {p['panel2']}; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 5px 8px; background: transparent; }}
QListWidget::item:selected {{ background: {p['seleccion']}; }}
QListWidget::item:hover {{ background: {p['panel2']}; }}
QCheckBox {{ color: {p['texto']}; spacing: 6px; }}
QSplitter::handle {{ background: {p['borde']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p['borde']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {p['borde']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QTabWidget::pane {{ background: transparent; border: none; }}
QToolBar#navigationToolbar {{ background: transparent; border: none; padding: 0px 8px; }}
QFrame#inicioContext, QFrame#referenceControls {{
    background: {p['panel2']}; border: 1px solid {p['borde']}; border-radius: {RADIUS_PANEL}px;
}}
QTabBar {{
    background: transparent; border: none; border-bottom: 1px solid {p['borde']};
    padding: 4px 8px;
}}
QTabBar::tab {{
    background: transparent; color: {p['texto2']}; padding: 12px 24px;
    border: none; border-radius: 0; border-bottom: 2px solid transparent;
    margin: 0 8px;
}}
QTabBar::tab:selected {{
    background: transparent; color: {p['texto']}; font-weight: 700;
    border-bottom: 2px solid {p['acento']};
}}
QTabBar::tab:hover {{ background: transparent; color: {p['texto']}; }}
QTabBar::tab:pressed {{ background: transparent; }}
QTabBar::tab:focus {{ outline: none; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: transparent; color: {p['texto']}; padding: 4px 6px;
    border: none; border-bottom: 1px solid {p['borde']};
}}
QHeaderView::section:hover {{ background: transparent; }}
QHeaderView::section:pressed {{ background: transparent; }}
"""


_APPLIED_THEME: str | None = None


def apply_common_style(app, theme: str | None = None) -> None:
    global _APPLIED_THEME
    current = theme or load_preference()
    if _APPLIED_THEME == current:
        return
    _APPLIED_THEME = current
    app.setStyleSheet(common_stylesheet(current))
