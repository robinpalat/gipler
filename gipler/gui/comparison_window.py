"""Ventana independiente de comparación (doble clic).

Reutiliza diff_view.DiffViewer (dos columnas, colores, scroll
sincronizado). Casos: texto, binario (metadatos), idéntico (mensaje),
nuevo/ausente (contraparte ausente), errores de lectura.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gipler.comparator import make_diff
from gipler.gui.diff_view import DiffViewer
from gipler.gui.identity import apply_window_icon
from gipler.report import Row


DEFAULT_DIFF_GEOMETRY = QRect(0, 0, 1240, 800)
MIN_DIFF_WIDTH = 480
MIN_DIFF_HEIGHT = 320
SAFE_MARGIN = 24


def _overlap_area(rect: QRect, area: QRect) -> int:
    intersection = rect.intersected(area)
    if intersection.isEmpty():
        return 0
    return intersection.width() * intersection.height()


def _screen_for_rect(rect: QRect):
    screens = QGuiApplication.screens()
    if not screens:
        return None
    return max(screens, key=lambda screen: _overlap_area(rect, screen.availableGeometry()))


def _safe_geometry(screen) -> QRect:
    area = screen.availableGeometry()
    width = min(
        DEFAULT_DIFF_GEOMETRY.width(),
        max(MIN_DIFF_WIDTH, area.width() - 2 * SAFE_MARGIN),
    )
    height = min(
        DEFAULT_DIFF_GEOMETRY.height(),
        max(MIN_DIFF_HEIGHT, area.height() - 2 * SAFE_MARGIN),
    )
    width = min(width, area.width())
    height = min(height, area.height())
    return QRect(
        area.x() + (area.width() - width) // 2,
        area.y() + (area.height() - height) // 2,
        width,
        height,
    )


def _clamp_geometry(rect: QRect, area: QRect) -> QRect:
    width = min(rect.width(), area.width())
    height = min(rect.height(), area.height())
    x = min(max(rect.x(), area.left()), area.right() - width + 1)
    y = min(max(rect.y(), area.top()), area.bottom() - height + 1)
    return QRect(x, y, width, height)


def _geometry_is_usable(rect: QRect, area: QRect) -> bool:
    if rect.width() < MIN_DIFF_WIDTH or rect.height() < MIN_DIFF_HEIGHT:
        return False
    visible = rect.intersected(area)
    if visible.width() < 160 or visible.height() < 120:
        return False
    title_bar = QRect(rect.x(), rect.y(), rect.width(), min(40, rect.height()))
    return not title_bar.intersected(area).isEmpty()


class ComparisonWindow(QMainWindow):
    def __init__(self, row: Row, dev_root: str, repo_root: str, parent=None):
        super().__init__(parent)
        apply_window_icon(self)
        self.row = row
        self.dev_root = dev_root
        self.repo_root = repo_root
        from gipler.config import get_settings

        s = get_settings()
        geometry = s.value("diff_window/geometry")
        state = s.value("diff_window/state")
        restored = bool(geometry) and self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        if restored:
            self._ensure_visible_geometry()
        else:
            self._apply_safe_geometry()
        self.setWindowTitle(f"{row.path}")
        from gipler.gui.comparison_header import summary_text

        title_text = summary_text(row)
        from PySide6.QtWidgets import QLabel

        title_label = QLabel(title_text)
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.diff = DiffViewer()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en diferencias…")
        self.search.setFixedWidth(280)
        self.search.setVisible(False)
        self.search.textChanged.connect(self._find)
        self.search_close = QToolButton()
        self.search_close.setText("×")
        self.search_close.setToolTip("Cerrar búsqueda")
        self.search_close.setAccessibleName("Cerrar búsqueda")
        self.search_close.setAutoRaise(True)
        self.search_close.setFixedSize(24, 24)
        self.search_close.setVisible(False)
        self.search_close.clicked.connect(self._close_search)
        self.search_button = QToolButton()
        search_icon = QIcon.fromTheme("edit-find")
        if search_icon.isNull():
            self.search_button.setText("⌕")
        else:
            self.search_button.setIcon(search_icon)
        self.search_button.setToolTip("Buscar en diferencias (Ctrl+F)")
        self.search_button.setAccessibleName("Buscar en diferencias")
        self.search_button.setAutoRaise(True)
        self.search_button.setFixedSize(28, 28)
        self.search_button.clicked.connect(self._toggle_search)
        compact_button_style = (
            "QToolButton { border: none; background: transparent; padding: 2px; }"
        )
        self.search_button.setStyleSheet(compact_button_style)
        self.search_close.setStyleSheet(compact_button_style)
        self.search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.search_shortcut.activated.connect(self._open_search)
        self.vertical_splitter = QSplitter(Qt.Vertical)
        info_box = QWidget()
        vert = QVBoxLayout(info_box)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        header_row.addWidget(title_label, 1)
        header_row.addWidget(self.search)
        header_row.addWidget(self.search_close)
        header_row.addWidget(self.search_button)
        vert.addLayout(header_row)
        vert.addStretch(1)
        self.vertical_splitter.addWidget(info_box)
        self.vertical_splitter.addWidget(self.diff)
        self.vertical_splitter.setChildrenCollapsible(False)
        self.vertical_splitter.setStretchFactor(0, 0)
        self.vertical_splitter.setStretchFactor(1, 1)
        vs_state = s.value("diff_window/vertical_splitter_state")
        if vs_state:
            self.vertical_splitter.restoreState(vs_state)
        else:
            self.vertical_splitter.setSizes([90, 710])
        self.vertical_splitter.splitterMoved.connect(self._on_vsplit_moved)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.vertical_splitter)
        self.setCentralWidget(central)
        self._fill()

    def _apply_safe_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.setGeometry(DEFAULT_DIFF_GEOMETRY)
            return
        self.setGeometry(_safe_geometry(screen))

    def _ensure_visible_geometry(self) -> None:
        frame = self.frameGeometry()
        screen = _screen_for_rect(frame)
        if screen is None:
            self._apply_safe_geometry()
            return
        area = screen.availableGeometry()
        if not _geometry_is_usable(frame, area):
            self.setGeometry(_safe_geometry(screen))
            return
        clamped = _clamp_geometry(frame, area)
        if clamped != frame:
            self.setGeometry(clamped)

    def _open_search(self) -> None:
        self.search.setVisible(True)
        self.search_close.setVisible(True)
        self.search.setFocus()
        self.search.selectAll()

    def _close_search(self) -> None:
        self.search.clear()
        self.search.setVisible(False)
        self.search_close.setVisible(False)

    def _toggle_search(self) -> None:
        if self.search.isVisible():
            self._close_search()
        else:
            self._open_search()

    def _on_vsplit_moved(self, _, index) -> None:
        from gipler.config import get_settings

        s = get_settings()
        s.setValue("diff_window/vertical_splitter_state", self.vertical_splitter.saveState())
        # Guardar también la geometría general (ventana activa).
        s.setValue("diff_window/geometry", self.saveGeometry())
        s.setValue("diff_window/state", self.saveState())

    def closeEvent(self, event) -> None:
        from gipler.config import get_settings

        s = get_settings()
        s.setValue("diff_window/geometry", self.saveGeometry())
        s.setValue("diff_window/state", self.saveState())
        s.setValue("diff_window/vertical_splitter_state", self.vertical_splitter.saveState())
        s.setValue("diff_window/splitter_state", self.diff.splitter.saveState())
        s.sync()
        super().closeEvent(event)

    def _fill(self) -> None:
        r = self.row
        dev_path = os.path.join(self.dev_root, r.path)
        repo_path = os.path.join(self.repo_root, r.path) if self.repo_root else ""
        in_dev = os.path.lexists(dev_path)
        in_repo = bool(repo_path and os.path.lexists(repo_path))
        if in_dev and in_repo:
            # Binario en sentido operativo: contiene NUL o no es UTF-8.
            is_binary = False
            for p in (dev_path, repo_path):
                with open(p, "rb") as f:
                    data = f.read()
                if b"\x00" in data:
                    is_binary = True
                    break
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    is_binary = True
                    break
            if is_binary:
                from PySide6.QtWidgets import QListWidgetItem
                from gipler.gui.inspector import Inspector
                meta_lines = []
                for label, p in (("Dev", dev_path), ("Repo", repo_path)):
                    m = Inspector._meta(p)
                    meta_lines.append(f"{label}: " + ", ".join(f"{k}={v}" for k, v in m.items()))
                self.diff.left.clear()
                self.diff.right.clear()
                self.diff.left.addItem(QListWidgetItem("(binario — sin diff textual) " + " | ".join(meta_lines)))
                return
            if r.axis_a == "identical":
                self.diff.set_texts("", "")
                from PySide6.QtWidgets import QListWidgetItem
                self.diff.left.clear()
                self.diff.right.clear()
                self.diff.left.addItem(QListWidgetItem("(idéntico en ambos lados — sin diferencias)"))
                self.diff.right.addItem(QListWidgetItem("(idéntico en ambos lados — sin diferencias)"))
                return
            with open(dev_path, encoding="utf-8") as f:
                devt = f.read()
            with open(repo_path, encoding="utf-8") as f:
                repot = f.read()
            self.diff.set_texts(devt, repot, left="Dev", right="Repositorio")
        else:
            from PySide6.QtWidgets import QListWidgetItem

            self.diff.left.clear()
            self.diff.right.clear()
            if in_dev:
                msg = "(nuevo en Dev — sin contraparte en el repositorio)"
            elif in_repo:
                msg = "(ausente en Dev — solo existe en el repositorio)"
            else:
                msg = "(no disponible en ningún lado)"
            self.diff.left.addItem(QListWidgetItem(msg))
            self.diff.right.addItem(QListWidgetItem(msg))

    def _find(self) -> None:
        text = self.search.text()
        if text:
            self.diff.find_first(text)
