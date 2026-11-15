"""Sistema visual común de Gipler.

Define la paleta, los radios, el espaciado y los estilos compartidos por
Inicio, referencias, Excluidos e Indeterminados. Se aplica globalmente para
evitar QSS duplicado en cada pestaña.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QToolButton

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


class ContextIconButton(QToolButton):
    """Botón de icono compartido por las toolbars contextuales."""

    def __init__(
        self,
        icon_name: str,
        tooltip: str,
        parent=None,
        *,
        icon_size: int = 18,
        button_size: int = 28,
        icon_palette_key: str | None = None,
    ):
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_palette_key = icon_palette_key
        self.setObjectName("contextIconButton")
        self.setIconSize(QSize(icon_size, icon_size))
        self.setFixedSize(button_size, button_size)
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        from gipler.gui import icons

        color = None
        if self._icon_palette_key:
            color = palette().get(self._icon_palette_key)
        self.setIcon(icons.icon(self._icon_name, color))

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._refresh_icon()


def make_context_icon_button(
    icon_name: str,
    tooltip: str,
    parent=None,
    *,
    icon_size: int = 18,
    button_size: int = 28,
    icon_palette_key: str | None = None,
) -> ContextIconButton:
    return ContextIconButton(
        icon_name,
        tooltip,
        parent,
        icon_size=icon_size,
        button_size=button_size,
        icon_palette_key=icon_palette_key,
    )


def make_context_label(text: str = "") -> QLabel:
    """Información contextual compartida por Sincronización y Git.

    Es el mismo componente visual en ambas vistas: mismo objeto, estilo,
    tipografía, alineación, padding y posición relativa a sus controles.
    """
    label = QLabel(text)
    label.setObjectName("contextInfoLabel")
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
QLabel#contextInfoLabel {{ color: {p['texto2']}; font-size: 12px; font-weight: 500; padding: 4px 8px; }}
QLabel#emptyState {{ color: {p['texto2']}; font-size: 12px; background: transparent; }}
QLabel#aboutVersion {{ color: {p['texto2']}; font-size: 12px; }}
QLabel#aboutDescription {{ color: {p['texto']}; font-size: 12px; }}
QLabel#aboutLicense {{ color: {p['texto2']}; font-size: 11px; }}
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
QToolButton#contextIconButton {{
    background: transparent; border: none; padding: 0px; border-radius: 4px;
}}
QToolButton#contextIconButton:hover {{ background: rgba(127, 127, 127, 0.12); }}
QToolButton#contextIconButton:pressed,
QToolButton#contextIconButton:checked {{ background: rgba(127, 127, 127, 0.18); }}
QToolButton#contextIconButton:disabled {{ background: transparent; }}
QToolButton#globalIconButton {{
    background: transparent; border: none; padding: 0px; border-radius: 4px;
}}
QToolButton#globalIconButton:hover {{ background: rgba(127, 127, 127, 0.18); }}
QToolButton#globalIconButton:pressed,
QToolButton#globalIconButton:checked {{ background: rgba(127, 127, 127, 0.24); }}
QToolButton#globalIconButton:disabled {{ background: transparent; }}
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
QTreeView#semanticTree::item {{ padding: 3px 4px; }}
QTreeView#referenceTree {{ padding-left: 6px; }}
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
