"""Panel explorador (Fase 2: QTreeView sincronizado)."""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from gipler.gui import icons
from gipler.gui.git_bar import ElidedLabel

from gipler.gui.models.filter_model import FilterModel
from gipler.selection import selection_key_for

DEV_HEADERS = ("Nombre", "Estado del destino", "Advertencias")
REPO_HEADERS = ("Nombre", "Estado Git", "Advertencias")


class DirectoryHeaderTitle(ElidedLabel):
    """Etiqueta de directorio que se dimensiona a su texto y elide si no cabe."""

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(
            self.fontMetrics().horizontalAdvance(self.full_text()) + 8,
            self.fontMetrics().height(),
        )

    def setText(self, text: str, tooltip: str | None = None) -> None:  # type: ignore[override]
        super().setText(text, tooltip)
        self.updateGeometry()


class PanelProxy(FilterModel):
    """Proxy por panel: misma lógica de filtro, cabeceras propias."""

    def __init__(self, headers: tuple[str, ...], parent=None):
        super().__init__(parent)
        self._headers = headers
        self.physical_side = ""
        self.dev_root = ""
        self.repo_root = ""
        self.base_root = ""

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
        if (
            role == Qt.DisplayRole
            and index.isValid()
            and index.column() == 0
            and self.physical_side == "dev"
        ):
            source = self.sourceModel()
            source_index = self.mapToSource(index)
            node = source.node_at(source_index) if hasattr(source, "node_at") else None
            if node is not None:
                return node.name
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
    copy_requested = Signal(object, str)
    delete_requested = Signal(object, str)
    discard_requested = Signal(object, str)
    select_all_commit_changed = Signal(int)
    commit_requested = Signal()
    commit_confirmed = Signal(str)
    commit_cancelled = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.is_dev = title == "Dev"
        self.directory_header = QFrame()
        self.directory_header.setObjectName("directoryHeader")
        self.directory_header.setFrameShape(QFrame.Shape.NoFrame)
        self.directory_header.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed
        )
        self.header = QHBoxLayout(self.directory_header)
        self.header.setContentsMargins(10, 2, 10, 2)
        self.header.setSpacing(6)
        self.folder_icon = QLabel()
        self.folder_icon.setVisible(True)
        self.folder_icon.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self._folder_icon_color = icons.current_color()
        self._folder_icon_pending = False
        self._refresh_folder_icon(force=True)
        self.folder_icon.setAccessibleName("Directorio")
        self.title_label = DirectoryHeaderTitle(title)
        self.title_label.setObjectName("directoryHeaderTitle")
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header_font = self.title_label.font()
        header_font.setWeight(QFont.Weight.DemiBold)
        header_font.setPointSizeF(header_font.pointSizeF() + 0.5)
        self.title_label.setFont(header_font)
        self.header.addWidget(self.folder_icon, 0, Qt.AlignVCenter)
        self.header.addWidget(self.title_label, 0, Qt.AlignVCenter)
        self._header_extra = None
        self.tree = QTreeView()
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        if not self.is_dev:
            self.tree.setObjectName("referenceTree")
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 170)
        self.tree.setColumnWidth(2, 220)
        header = self.tree.header()
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self._headers = DEV_HEADERS if self.is_dev else REPO_HEADERS
        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setVisible(False)
        self.content = QWidget()
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self._build_commit_controls()
        content_layout.addWidget(self.commit_bar)
        content_layout.addWidget(self.commit_warning)
        content_layout.addWidget(self.commit_error)
        content_layout.addWidget(self.commit_message_row)
        content_layout.addWidget(self.tree, 1)
        content_layout.addWidget(self.empty_label, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.addWidget(self.directory_header, 0, Qt.AlignLeft)
        layout.addWidget(self.content, 1)

    def _build_commit_controls(self) -> None:
        self.commit_bar = QWidget()
        commit_layout = QHBoxLayout(self.commit_bar)
        commit_layout.setContentsMargins(0, 0, 0, 0)
        self.select_all_commit = QCheckBox("Seleccionar todos")
        self.select_all_commit.setTristate(True)
        self.commit_count_label = QLabel("")
        self.commit_button = QPushButton("Confirmar selección")
        self.commit_button.setToolTip(
            "Confirmar un commit con los archivos seleccionados en esta vista"
        )
        self.commit_button.setEnabled(False)
        commit_layout.addWidget(self.select_all_commit)
        commit_layout.addWidget(self.commit_count_label)
        commit_layout.addStretch(1)
        commit_layout.addWidget(self.commit_button)
        self.commit_bar.setVisible(False)

        self.commit_warning = QLabel()
        self.commit_warning.setWordWrap(True)
        self.commit_warning.setVisible(False)
        self.commit_error = QLabel()
        self.commit_error.setWordWrap(True)
        self.commit_error.setVisible(False)
        self.commit_error.setStyleSheet("color: #C0504D;")

        self.commit_message_row = QWidget()
        message_layout = QVBoxLayout(self.commit_message_row)
        message_layout.setContentsMargins(0, 0, 0, 0)
        top_row = QHBoxLayout()
        self.commit_message_edit = QLineEdit()
        self.commit_message_edit.setPlaceholderText("Mensaje del commit...")
        self.commit_message_edit.setAccessibleName("Mensaje del commit")
        self.commit_confirm_button = QPushButton("Confirmar")
        self.commit_cancel_button = QPushButton("Cancelar")
        top_row.addWidget(self.commit_message_edit, 1)
        top_row.addWidget(self.commit_confirm_button)
        top_row.addWidget(self.commit_cancel_button)
        self.commit_include_staged = QCheckBox(
            "Incluir archivos previamente preparados"
        )
        self.commit_include_staged.setVisible(False)
        message_layout.addLayout(top_row)
        message_layout.addWidget(self.commit_include_staged)
        self.commit_message_row.setVisible(False)

        self.select_all_commit.stateChanged.connect(
            self.select_all_commit_changed
        )
        self.commit_button.clicked.connect(self.commit_requested)
        self.commit_confirm_button.clicked.connect(
            lambda: self.commit_confirmed.emit(self.commit_message_edit.text())
        )
        self.commit_cancel_button.clicked.connect(self.commit_cancelled)

    def set_commit_mode(self, enabled: bool) -> None:
        self.commit_bar.setVisible(enabled)
        if not enabled:
            self.reset_commit_form()

    def set_commit_count(self, text: str) -> None:
        self.commit_count_label.setText(text)

    def set_commit_enabled(self, enabled: bool) -> None:
        self.commit_button.setEnabled(bool(enabled))

    def set_select_all_state(
        self, visible_eligible: set[str], selected: set[str]
    ) -> None:
        self.select_all_commit.setEnabled(bool(visible_eligible))
        self.select_all_commit.blockSignals(True)
        if not visible_eligible:
            self.select_all_commit.setCheckState(Qt.CheckState.Unchecked)
        elif visible_eligible <= selected:
            self.select_all_commit.setCheckState(Qt.CheckState.Checked)
        elif selected & visible_eligible:
            self.select_all_commit.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.select_all_commit.setCheckState(Qt.CheckState.Unchecked)
        self.select_all_commit.blockSignals(False)

    def set_commit_warning(self, text: str) -> None:
        self.commit_warning.setText(text or "")
        self.commit_warning.setVisible(bool(text))

    def set_commit_error(self, text: str) -> None:
        self.commit_error.setText(text or "")
        self.commit_error.setVisible(bool(text))

    def set_include_staged_visible(self, visible: bool) -> None:
        self.commit_include_staged.setVisible(bool(visible))
        if not visible:
            self.commit_include_staged.setChecked(False)

    def commit_include_staged_checked(self) -> bool:
        return self.commit_include_staged.isChecked()

    def set_commit_message_visible(self, visible: bool) -> None:
        self.commit_message_row.setVisible(bool(visible))

    def clear_commit_message(self) -> None:
        self.commit_message_edit.clear()

    def focus_commit_message(self) -> None:
        self.commit_message_edit.setFocus()

    def reset_commit_form(self) -> None:
        self.commit_message_edit.clear()
        self.commit_include_staged.setChecked(False)
        self.commit_message_row.setVisible(False)
        self.commit_warning.setVisible(False)
        self.commit_error.setVisible(False)

    def set_empty_message(self, text: str = "") -> None:
        self.empty_label.setText(text or "")
        self.empty_label.setVisible(bool(text))
        self.tree.setVisible(not text)

    def _refresh_folder_icon(self, *, force: bool = False) -> None:
        color = icons.current_color()
        if not force and color == self._folder_icon_color:
            return
        self._folder_icon_color = color
        self.folder_icon.setPixmap(icons.icon("folder").pixmap(QSize(16, 16)))

    def _refresh_folder_icon_deferred(self) -> None:
        self._folder_icon_pending = False
        self._refresh_folder_icon()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            if self._folder_icon_pending:
                return
            self._folder_icon_pending = True
            QTimer.singleShot(0, self._refresh_folder_icon_deferred)

    def set_title(self, title: str, tooltip: str = "") -> None:
        self.title_label.setText(title)
        self.title_label.setToolTip(tooltip or title)

    def set_reference_mode(self, enabled: bool = True) -> None:
        self.folder_icon.setVisible(enabled)

    def set_header_extra(self, widget: QWidget, stretch: int = 2) -> None:
        if self._header_extra is not None:
            self.header.removeWidget(self._header_extra)
        self._header_extra = widget
        self.header.addWidget(widget, stretch, Qt.AlignVCenter)

    def set_model(self, model) -> None:
        self.tree.setModel(model)
        self._apply_widths()

    def _apply_widths(self) -> None:
        """Anchos una vez el modelo existe (QHeaderView los reinicia)."""
        header = self.tree.header()
        header.setMinimumSectionSize(70)
        header.setVisible(True)
        if self.is_dev:
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
        self.set_empty_message("")
        self.set_commit_mode(False)

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
        return None if node is None else (node.path, node.is_dir, node.row)

    def _open_context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if index.isValid():
            menu = QMenu(self)
            resolved = self._resolve(index)
            if resolved is None:
                return
            rel, is_dir, row = resolved
            side = "dev" if self.is_dev else "repo"
            if not is_dir and row is not None:
                copy_action = menu.addAction(
                    f"Copiar a {self._copy_target_name(row, side)}"
                )
                copy_key = (
                    selection_key_for(row)
                    if side == "dev"
                    else self._reverse_copy_key(row)
                )
                copy_action.setEnabled(copy_key is not None)
                copy_action.triggered.connect(
                    lambda: self.copy_requested.emit(row, side)
                )
            open_action = menu.addAction("Abrir en explorador")
            open_action.triggered.connect(lambda: self._open_in_explorer(rel, is_dir))
            menu.addAction("Excluir").triggered.connect(lambda: self.exclude_requested.emit(rel))
            if not is_dir and row is not None:
                menu.addSeparator()
                if self._discard_candidate(row):
                    discard_action = menu.addAction("Descartar cambios de Git…")
                    discard_action.triggered.connect(
                        lambda: self.discard_requested.emit(row, side)
                    )
                delete_action = menu.addAction("Eliminar…")
                delete_action.triggered.connect(
                    lambda: self.delete_requested.emit(row, side)
                )
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _copy_target_name(self, row, side: str) -> str:
        win = self.window()
        if side == "repo":
            root = getattr(win, "meta", {}).get("dev", "")
        elif hasattr(win, "_repo_root_for"):
            root = win._repo_root_for(row.destination)
        else:
            root = ""
        if root:
            name = os.path.basename(os.path.normpath(root))
            if name:
                return name
        return "Dev" if side == "repo" else (row.destination or "referencia")

    @staticmethod
    def _reverse_copy_key(row):
        if row.axis_a not in ("modified_in_dev", "missing_in_dev"):
            return None
        if not row.destination or not row.path:
            return None
        return row.destination, row.path

    @staticmethod
    def _discard_candidate(row) -> bool:
        statuses = set(getattr(row, "git_statuses", ()) or ())
        return bool(
            row.axis_b == "tracked_modified"
            or getattr(row, "git_change", "")
            or getattr(row, "git_stage", "")
            or statuses & {"modified_unstaged", "staged"}
        )

    def _explorer_base(self) -> str:
        base_root = getattr(self, "base_root", "")
        if base_root:
            return base_root
        win = self.window()
        meta = getattr(win, "meta", None)
        if not meta:
            return ""
        if self.is_dev:
            return meta.get("dev", "")
        proxy = self.tree.model()
        if proxy is not None and getattr(proxy, "physical_side", "") == "repo":
            return getattr(proxy, "repo_root", "")
        return meta.get("principal", "")

    def _open_in_explorer(self, rel: str, is_dir: bool) -> None:
        import os
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        base = self._explorer_base()
        target = os.path.join(base, rel)
        if not is_dir:
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
        elif win is not None and win.statusBar() is not None:
            win.statusBar().showMessage(message)
