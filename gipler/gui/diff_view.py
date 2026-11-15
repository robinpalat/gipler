"""Visor de diferencias en dos paneles con QSplitter (Fase pre-Qt).

Dev a la izquierda, repositorio a la derecha, con QSplitter
horizontal persistido en QSettings. Desplazamiento vertical
sincronizado; horizontal independiente. Resalta diferencias
(inserción/eliminación/reemplazo con numeración de líneas).
"""
from __future__ import annotations

import difflib
import os

from PySide6.QtCore import QEvent, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


DIFF_LINE_ROLE = Qt.UserRole + 10


class _DiffItemDelegate(QStyledItemDelegate):
    """Pinta fondo y texto por línea sin que el QSS los vuelva transparentes."""

    def paint(self, painter, option, index) -> None:
        painter.save()
        background = index.data(Qt.BackgroundRole)
        painter.fillRect(
            option.rect,
            background if background is not None else option.palette.base(),
        )
        foreground = index.data(Qt.ForegroundRole)
        color = (
            foreground.color()
            if foreground is not None
            else option.palette.text().color()
        )
        text = str(index.data(Qt.DisplayRole) or "")
        if not index.data(DIFF_LINE_ROLE):
            painter.setFont(option.font)
            painter.setPen(color)
            painter.drawText(
                option.rect.adjusted(8, 0, -8, 0),
                int(Qt.AlignLeft | Qt.AlignVCenter),
                text,
            )
            painter.restore()
            return
        marker = text[:1]
        number = text[2:7]
        code = text[9:]
        metrics = option.fontMetrics
        char_width = metrics.horizontalAdvance("0")
        left = option.rect.left() + 8
        marker_x = left
        number_x = left + 2 * char_width
        code_x = left + 9 * char_width
        number_width = 7 * char_width

        gutter = QColor(option.palette.color(QPalette.ColorRole.AlternateBase))
        gutter.setAlpha(90)
        painter.fillRect(
            QRect(number_x, option.rect.top(), number_width, option.rect.height()),
            gutter,
        )
        divider = QColor(option.palette.color(QPalette.ColorRole.Mid))
        divider.setAlpha(110)
        painter.setPen(divider)
        painter.drawLine(
            code_x - 1,
            option.rect.top() + 2,
            code_x - 1,
            option.rect.bottom() - 2,
        )

        painter.setFont(option.font)
        painter.setPen(color if marker.strip() else option.palette.text().color())
        painter.drawText(
            QRect(marker_x, option.rect.top(), 2 * char_width, option.rect.height()),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            marker,
        )
        painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            QRect(number_x, option.rect.top(), 5 * char_width, option.rect.height()),
            int(Qt.AlignRight | Qt.AlignVCenter),
            number.strip(),
        )
        painter.setPen(color)
        painter.drawText(
            QRect(
                code_x,
                option.rect.top(),
                max(0, option.rect.right() - 8 - code_x),
                option.rect.height(),
            ),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            code,
        )
        painter.restore()


class _Pane(QListWidget):
    def __init__(self):
        super().__init__()
        self.setSelectionMode(QListWidget.NoSelection)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.setFont(font)
        self.font_size_ok = True


def _lines_of(title: str, counter: int) -> str:
    return f"{title} {counter}"


DIFF_THEME_COLORS = {
    "oscuro": {
        "added_bg": "#243B2E",
        "added_fg": "#A7E3B3",
        "removed_bg": "#42262A",
        "removed_fg": "#F0B0B4",
    },
    "claro": {
        "added_bg": "#E3F4E7",
        "added_fg": "#14532D",
        "removed_bg": "#FBE4E5",
        "removed_fg": "#7F1D1D",
    },
}


class DiffViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.splitter = QSplitter(Qt.Horizontal)
        self.left = _Pane()
        self.right = _Pane()
        for pane in (self.left, self.right):
            pane.setItemDelegate(_DiffItemDelegate(pane))
        self._last_texts: tuple[str, str, str, str] | None = None
        for pane, title in ((self.left, "Dev"), (self.right, "Repositorio")):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            from PySide6.QtWidgets import QLabel

            layout = QVBoxLayout(frame)
            layout.addWidget(QLabel(title))
            layout.addWidget(pane)
            self.splitter.addWidget(frame)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        # Restaurar última proporción (si existe).
        from gipler.config import get_settings

        s = get_settings()
        saved = s.value("diff_window/splitter_state")
        if saved:
            self.splitter.restoreState(saved)
        self.splitter.splitterMoved.connect(self._on_split_moved)
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)
        # Sincronizar scroll vertical.
        self.left.verticalScrollBar().valueChanged.connect(self.right.verticalScrollBar().setValue)
        self.right.verticalScrollBar().valueChanged.connect(self.left.verticalScrollBar().setValue)

    def _on_split_moved(self, _, index) -> None:
        from gipler.config import get_settings

        s = get_settings()
        s.setValue("diff_window/splitter_state", self.splitter.saveState())

    def _diff_colors(self) -> dict[str, str]:
        from gipler.gui.theme import load_preference

        theme = load_preference()
        return DIFF_THEME_COLORS.get(theme, DIFF_THEME_COLORS["oscuro"])

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        last_texts = getattr(self, "_last_texts", None)
        if event.type() == QEvent.Type.PaletteChange and last_texts is not None:
            scroll = (
                self.left.verticalScrollBar().value(),
                self.right.verticalScrollBar().value(),
                self.left.horizontalScrollBar().value(),
                self.right.horizontalScrollBar().value(),
            )
            self.set_texts(*last_texts)
            self.left.verticalScrollBar().setValue(scroll[0])
            self.right.verticalScrollBar().setValue(scroll[1])
            self.left.horizontalScrollBar().setValue(scroll[2])
            self.right.horizontalScrollBar().setValue(scroll[3])

    # API ---------------------------------------------------------
    def set_texts(self, dev_text: str, repo_text: str, left="Dev", right="Repositorio") -> None:
        """Alinea dos textos por opcodes y pinta las diferencias."""
        self._last_texts = (dev_text, repo_text, left, right)
        colors = self._diff_colors()
        added_bg = QColor(colors["added_bg"])
        added_fg = QColor(colors["added_fg"])
        removed_bg = QColor(colors["removed_bg"])
        removed_fg = QColor(colors["removed_fg"])
        dev_lines = dev_text.splitlines()
        repo_lines = repo_text.splitlines()
        self.left.clear()
        self.right.clear()
        if dev_lines == repo_lines:
            i = QListWidgetItem("(idéntico en ambos lados)")
            self.left.addItem(i)
            pass  # (stop eliminado)
            return
        sm = difflib.SequenceMatcher(a=repo_lines, b=dev_lines)
        ln = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            def add_left(text, bg=None, fg=None, marker=""):
                prefix = f"{marker} " if marker else "  "
                item = QListWidgetItem(
                    f"{prefix}{ln:5d}  {text}" if text else f"{prefix}{ln:5d}"
                )
                if bg:
                    item.setBackground(bg)
                if fg:
                    item.setForeground(fg)
                item.setData(DIFF_LINE_ROLE, True)
                self.left.addItem(item)

            def add_right(text, bg=None, fg=None, marker=""):
                prefix = f"{marker} " if marker else "  "
                item = QListWidgetItem(
                    f"{prefix}{ln:5d}  {text}" if text else f"{prefix}{ln:5d}"
                )
                if bg:
                    item.setBackground(bg)
                if fg:
                    item.setForeground(fg)
                item.setData(DIFF_LINE_ROLE, True)
                self.right.addItem(item)

            if tag == "equal":
                for k in range(i2 - i1):
                    ln += 1
                    add_left(dev_lines[j1 + k])
                    add_right(repo_lines[i1 + k])
            elif tag == "delete":
                for k in range(i2 - i1):
                    ln += 1
                    add_left("")
                    add_right(repo_lines[i1 + k], removed_bg, removed_fg, "−")
            elif tag == "insert":
                for k in range(j2 - j1):
                    ln += 1
                    add_left(dev_lines[j1 + k], added_bg, added_fg, "+")
                    add_right("")
            elif tag == "replace":
                nd, nr = max(i2 - i1, j2 - j1), max(i2 - i1, j2 - j1)
                max_n = max(i2 - i1, j2 - j1)
                for k in range(max_n):
                    ln += 1
                    has_left = j1 + k < j2
                    has_right = i1 + k < i2
                    dl = dev_lines[j1 + k] if has_left else ""
                    rl = repo_lines[i1 + k] if has_right else ""
                    add_left(
                        dl,
                        added_bg if has_left else None,
                        added_fg if has_left else None,
                        "+" if has_left else "",
                    )
                    add_right(
                        rl,
                        removed_bg if has_right else None,
                        removed_fg if has_right else None,
                        "−" if has_right else "",
                    )
        self.left.scrollToTop()
        self.right.scrollToTop()

    # Búsqueda ----------------------------------------------------
    def row_count(self) -> int:
        return self.left.count()

    def column_count(self) -> int:
        return 2
