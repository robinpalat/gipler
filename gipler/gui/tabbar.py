"""Barra de pestañas editorial para el QTabWidget principal.

Solo controla la presentación: texto, espaciado e indicador inferior.
No altera navegación, señales ni comportamiento de QTabWidget.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QSize
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QTabBar


class EditorialTabBar(QTabBar):
    HEIGHT = 44
    MIN_HEIGHT = 40
    # Padding horizontal total reservado en paintEvent (20 px por lado).
    TEXT_PADDING = 44
    MIN_WIDTH = 110

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setDrawBase(False) if hasattr(self, "setDrawBase") else None
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)

    def _text_width(self, index: int) -> int:
        """Ancho del texto con la fuente realmente pintada: la pestaña activa
        se destaca en negrita y +0.5 pt, y su texto es más ancho."""
        font = QFont(self.font())
        if index == self.currentIndex():
            font.setBold(True)
            font.setPointSize(self.font().pointSize() + 0.5)
        return QFontMetrics(font).horizontalAdvance(self.tabText(index))

    def tabSizeHint(self, index: int) -> QSize:
        width = self._text_width(index) + self.TEXT_PADDING
        return QSize(max(width, self.MIN_WIDTH), self.HEIGHT)

    def minimumTabSizeHint(self, index: int) -> QSize:
        # El mínimo garantiza que el texto completo siga visible (con el
        # padding de pintado) sin reservar más ancho del necesario.
        width = self._text_width(index) + self.TEXT_PADDING
        return QSize(max(width, 64), self.MIN_HEIGHT)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        hover_index = self.tabAt(self.mapFromGlobal(QCursor.pos()))
        for index in range(self.count()):
            rect = self.tabRect(index)
            if rect.isNull() or rect.isEmpty():
                continue
            selected = index == self.currentIndex()
            enabled = self.isTabEnabled(index)
            hovered = index == hover_index and not selected
            text = self.tabText(index)
            font = QFont(self.font())
            font.setBold(selected)
            if selected:
                font.setPointSize(self.font().pointSize() + 0.5)
            painter.setFont(font)
            if not enabled:
                color = self.palette().color(
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.Text,
                )
            elif selected:
                color = self.palette().color(QPalette.ColorRole.Text)
            elif hovered:
                color = self.palette().color(QPalette.ColorRole.Text)
            else:
                color = self.palette().color(
                    QPalette.ColorRole.PlaceholderText
                )
            painter.setPen(color)
            text_rect = rect.adjusted(20, 0, -20, 0)
            fm = QFontMetrics(font)
            text = fm.elidedText(
                text, Qt.TextElideMode.ElideRight, text_rect.width()
            )
            painter.drawText(
                text_rect, int(Qt.AlignmentFlag.AlignCenter), text
            )
            if selected:
                accent = self.palette().color(QPalette.ColorRole.Accent)
                painter.setPen(QPen(accent, 2))
                painter.drawLine(
                    int(rect.left() + 20),
                    int(rect.bottom() - 1),
                    int(rect.right() - 20),
                    int(rect.bottom() - 1),
                )
        painter.end()
