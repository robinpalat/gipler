"""Botón de navegación editorial para la barra superior principal.

Solo controla la presentación: texto transparente e indicador inferior.
No altera navegación, señales ni comportamiento.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QPushButton


class EditorialNavButton(QPushButton):
    HEIGHT = 44
    MIN_HEIGHT = 40
    # Padding horizontal total reservado en paintEvent (20 px por lado).
    TEXT_PADDING = 44

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy(),
        )

    def _text_width(self) -> int:
        """Ancho máximo entre el estado normal y el activo."""
        font = QFont(self.font())
        normal = QFontMetrics(font).horizontalAdvance(self.text())
        active = QFont(font)
        active.setBold(True)
        active.setPointSize(self.font().pointSize() + 0.5)
        return max(normal, QFontMetrics(active).horizontalAdvance(self.text()))

    def sizeHint(self) -> QSize:
        return QSize(self._text_width() + self.TEXT_PADDING, self.HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._text_width() + self.TEXT_PADDING, self.MIN_HEIGHT)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        checked = self.isChecked()
        enabled = self.isEnabled()
        hovered = self.underMouse() and not checked
        font = QFont(self.font())
        font.setBold(checked)
        if checked:
            font.setPointSize(self.font().pointSize() + 0.5)
        painter.setFont(font)
        if not enabled:
            color = self.palette().color(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Text,
            )
        elif checked or hovered:
            color = self.palette().color(QPalette.ColorRole.Text)
        else:
            color = self.palette().color(QPalette.ColorRole.PlaceholderText)
        painter.setPen(color)
        rect = self.rect().adjusted(20, 0, -20, 0)
        fm = QFontMetrics(font)
        text = fm.elidedText(
            self.text(), Qt.TextElideMode.ElideRight, rect.width()
        )
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
        if checked:
            accent = self.palette().color(QPalette.ColorRole.Accent)
            painter.setPen(QPen(accent, 2))
            painter.drawLine(
                int(self.rect().left() + 20),
                int(self.rect().bottom() - 1),
                int(self.rect().right() - 20),
                int(self.rect().bottom() - 1),
            )
        painter.end()
