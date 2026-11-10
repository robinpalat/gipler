"""Panel explorador (Fase 2: QTreeView sincronizado)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHeaderView, QLabel, QMenu, QTreeView, QVBoxLayout, QWidget

from gipler.gui.models.filter_model import FilterModel

DEV_HEADERS = ("Nombre", "Estado del destino", "Advertencias")
REPO_HEADERS = ("Nombre", "Estado Git", "Advertencias")


class PanelProxy(FilterModel):
    """Proxy por panel: misma lógica de filtro, cabeceras propias."""

    def __init__(self, headers: tuple[str, ...], parent=None):
        super().__init__(parent)
        self._headers = headers
        self.physical_side = ""
        self.dev_root = ""
        self.repo_root = ""

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.FontRole and index.isValid():
            source_index = self.mapToSource(index)
            source = self.sourceModel()
            node = source.node_at(source_index) if hasattr(source, "node_at") else None
            if node is not None and node.row is not None and not node.is_dir:
                root = self.dev_root if self.physical_side == "dev" else self.repo_root
                if root:
                    path = os.path.join(root, *node.path.split("/"))
                    if not os.path.lexists(path):
                        font = QFont(self.tree_font)
                        font.setStrikeOut(True)
                        return font
        return super().data(index, role)

    @property
    def tree_font(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.font()

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and section < len(self._headers):
            return self._headers[section]
        return super().headerData(section, orientation, role)


class ComparisonPanel(QWidget):
    exclude_requested = Signal(str)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title_label = QLabel(title)
        self.tree = QTreeView()
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 170)
        self.tree.setColumnWidth(2, 220)
        header = self.tree.header()
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self._headers = DEV_HEADERS if title == "Dev" else REPO_HEADERS
        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.tree)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        self._headers = DEV_HEADERS if title == "Dev" else REPO_HEADERS

    def set_model(self, model) -> None:
        self.tree.setModel(model)
        self._apply_widths()

    def _apply_widths(self) -> None:
        """Anchos una vez el modelo existe (QHeaderView los reinicia)."""
        header = self.tree.header()
        header.setMinimumSectionSize(70)
        header.setVisible(True)
        if self.title_label.text() == "Dev":
            self.tree.setColumnHidden(1, True)
            header.setSectionResizeMode(0, QHeaderView.Interactive)
            header.setSectionResizeMode(1, QHeaderView.Interactive)
            header.setSectionResizeMode(2, QHeaderView.Interactive)
            name_width = max(320, self.tree.viewport().width() - 180)
            self.tree.setColumnWidth(0, name_width)
            self.tree.setColumnWidth(2, 160)
        else:
            self.tree.setColumnHidden(1, False)
            header.setSectionResizeMode(0, QHeaderView.Interactive)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Interactive)
            self.tree.setColumnWidth(0, 320)
            self.tree.setColumnWidth(1, 180)
            self.tree.setColumnWidth(2, 140)

    def clear(self) -> None:
        self.tree.setModel(None)

    def _resolve(self, index):
        """Ruta relativa resolvida desde el índice proxy (fuente)."""
        model = self.tree.model()
        src = None
        try:
            src = model.mapToSource(index) if hasattr(model, "mapToSource") else index
        except Exception:
            src = index
        src_model = getattr(model, "sourceModel", lambda: model)() if hasattr(model, "sourceModel") else model
        node = src_model.node_at(src)
        return None if node is None else (node.path, node.is_dir)

    def _open_context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if index.isValid():
            menu = QMenu(self)
            resolved = self._resolve(index)
            if resolved is None:
                return
            rel, is_dir = resolved
            open_action = menu.addAction("Abrir en explorador")
            open_action.triggered.connect(lambda: self._open_in_explorer(rel, is_dir))
            menu.addAction("Excluir").triggered.connect(lambda: self.exclude_requested.emit(rel))
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _explorer_base(self) -> str:
        win = self.window()
        meta = getattr(win, "meta", None)
        if not meta:
            return ""
        return meta.get("dev", "") if self.title_label.text() == "Dev" else meta.get("principal", "")

    def _open_in_explorer(self, rel: str, is_dir: bool) -> None:
        import os
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        base = self._explorer_base()
        target = os.path.join(base, rel)
        if not is_dir and os.path.isfile(target):
            target = os.path.dirname(os.path.abspath(target))
        elif is_dir and os.path.isdir(target):
            target = os.path.abspath(target)
        if not os.path.isdir(target):
            self._report_error(f"No existe o no es un directorio: {target}")
            return
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(target)))
        if not ok:
            self._report_error(f"No se pudo abrir: {target}")

    def _report_error(self, message: str) -> None:
        win = self.window()
        if win is not None and hasattr(win, "status"):
            win.status.showMessage(message)
