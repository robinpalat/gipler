"""Visor de diferencias en dos paneles con QSplitter (Fase pre-Qt).

Dev a la izquierda, repositorio a la derecha, con QSplitter
horizontal persistido en QSettings. Desplazamiento vertical
sincronizado; horizontal independiente. Resalta diferencias
(inserción/eliminación/reemplazo con numeración de líneas).
"""
from __future__ import annotations

import difflib
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class _Pane(QListWidget):
    def __init__(self):
        super().__init__()
        self.setSelectionMode(QListWidget.NoSelection)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.setFont(font)
        self.font_size_ok = True


def _lines_of(title: str, counter: int) -> str:
    return f"{title} {counter}"


class DiffViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.splitter = QSplitter(Qt.Horizontal)
        self.left = _Pane()
        self.right = _Pane()
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

    # API ---------------------------------------------------------
    def set_texts(self, dev_text: str, repo_text: str, left="Dev", right="Repositorio") -> None:
        """Alinea dos textos por opcodes y pinta las diferencias."""
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
            def add_left(text, bg=None, fg=None, lnref=None):
                item = QListWidgetItem(f"{ln:5d}  {text}" if text else f"{ln:5d}")
                if bg:
                    item.setBackground(bg)
                if fg:
                    item.setForeground(fg)
                self.left.addItem(item)

            def add_right(text, bg=None, fg=None, lnref=None):
                item = QListWidgetItem(f"{ln:5d}  {text}" if text else f"{ln:5d}")
                if bg:
                    item.setBackground(bg)
                if fg:
                    item.setForeground(fg)
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
                    add_right(repo_lines[i1 + k], QColor("#F5DADA"), QColor("#542020"))
            elif tag == "insert":
                for k in range(j2 - j1):
                    ln += 1
                    add_left(dev_lines[j1 + k], QColor("#D8F0DA"), QColor("#173B20"))
                    add_right("")
            elif tag == "replace":
                nd, nr = max(i2 - i1, j2 - j1), max(i2 - i1, j2 - j1)
                max_n = max(i2 - i1, j2 - j1)
                for k in range(max_n):
                    ln += 1
                    dl = dev_lines[j1 + k] if j1 + k < j2 else ""
                    rl = repo_lines[i1 + k] if i1 + k < i2 else ""
                    add_left(dl, QColor("#D8F0DA"), QColor("#173B20"))
                    add_right(rl, QColor("#F5DADA"), QColor("#542020"))
        self.left.scrollToTop()
        self.right.scrollToTop()

    # Búsqueda ----------------------------------------------------
    def row_count(self) -> int:
        return self.left.count()

    def column_count(self) -> int:
        return 2
