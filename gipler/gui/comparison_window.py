"""Ventana independiente de comparación (doble clic).

Reutiliza diff_view.DiffViewer (dos columnas, colores, scroll
sincronizado). Casos: texto, binario (metadatos), idéntico (mensaje),
nuevo/ausente (contraparte ausente), errores de lectura.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QMainWindow, QSplitter, QVBoxLayout, QWidget

from gipler.comparator import make_diff
from gipler.gui.diff_view import DiffViewer
from gipler.report import Row

class ComparisonWindow(QMainWindow):
    def __init__(self, row: Row, dev_root: str, repo_root: str, parent=None):
        super().__init__(parent)
        self.row = row
        self.dev_root = dev_root
        self.repo_root = repo_root
        from gipler.config import get_settings

        s = get_settings()
        geometry = s.value("diff_window/geometry")
        state = s.value("diff_window/state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        if not geometry:
            self.resize(1240, 800)
        self.setWindowTitle(f"{row.path}")
        from gipler.gui.comparison_header import summary_text
        from gipler.gui.inspector import Inspector

        dev_m = Inspector._meta(os.path.join(dev_root, row.path))
        repo_path = (
            os.path.join(repo_root, row.path)
            if repo_root and row.destination in ("principal", "addons")
            else ""
        )
        repo_m = Inspector._meta(repo_path) if repo_path else {"existe": "sin destino"}
        title_text = summary_text(row, dev_m, repo_m)
        from PySide6.QtWidgets import QLabel

        title_label = QLabel(title_text)
        title_label.setWordWrap(True)
        self.diff = DiffViewer()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en diferencias…")
        self.search.textChanged.connect(self._find)
        self.vertical_splitter = QSplitter(Qt.Vertical)
        info_box = QWidget()
        vert = QVBoxLayout(info_box)
        vert.addWidget(title_label)
        self.vertical_splitter.addWidget(info_box)
        self.vertical_splitter.addWidget(self.diff)
        self.vertical_splitter.setChildrenCollapsible(False)
        self.vertical_splitter.setStretchFactor(0, 0)
        self.vertical_splitter.setStretchFactor(1, 1)
        vs_state = s.value("diff_window/vertical_splitter_state")
        if vs_state:
            self.vertical_splitter.restoreState(vs_state)
        self.vertical_splitter.splitterMoved.connect(self._on_vsplit_moved)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.search)
        layout.addWidget(self.vertical_splitter)
        self.setCentralWidget(central)
        self._fill()

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
