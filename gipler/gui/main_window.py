"""Ventana principal (Fases 1-5 spec GUI QT 1.0 + rediseño de usabilidad).

Distribución:
- Barra superior: selector de repositorio (segmentado) + acciones.
- Barra contextual con vista, filtros, búsqueda y estado operativo.
- Zona principal dominante: Dev | Repositorio | Inspector (QSplitter).
- Barra inferior informativa.
"""

from __future__ import annotations

import os

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QModelIndex
from gipler.gui.comparison_view import ComparisonPanel
from gipler.selection import (
    selection_key_for,
    selection_keys_for_path,
)
from gipler.gui.navbutton import EditorialNavButton
from gipler.gui.summary_panel import SummaryPanel
from gipler.gui.styles import make_context_label
from gipler.gui.models.comparison_tree import ComparisonTreeModel
from gipler.gui.models.filter_model import FilterModel, visible_file_count

AXIS_A = (
    "todos",
    "new_in_dev",
    "modified_in_dev",
    "identical",
    "missing_in_dev",
    "not_comparable",
    "diferencias",
    "git",
)
AXIS_B = ("todos", "tracked_modified", "tracked_clean", "untracked", "ignored", "incidencias")
AXIS_B_LABELS = {"incidencias": "Incidencias"}
GIT_AXIS_B = (
    "todos",
    "unstaged_changes",
    "modified_unstaged",
    "staged",
    "untracked",
    "ignored",
    "conflicts",
    "tracked_clean",
)
GIT_AXIS_B_LABELS = {
    "todos": "Todos los estados",
    "unstaged_changes": "Cambios sin preparar",
    "modified_unstaged": "Modificados sin preparar",
    "staged": "Preparados",
    "untracked": "Sin seguimiento",
    "ignored": "Ignorados",
    "conflicts": "Conflictos",
    "tracked_clean": "Tracked sin cambios",
}
CONFLICT_COMMIT_BLOCK = (
    "Commit bloqueado: hay conflictos sin resolver. Resuelva los conflictos "
    "y prepare los archivos explícitamente antes de confirmar."
)


class ProfileSwitchDialog(QDialog):
    """Diálogo sencillo para seleccionar y abrir otro perfil existente."""

    def __init__(self, window: "GiplerWindow"):
        super().__init__(window)
        self.window = window
        self.profile_id: str | None = None
        self.setWindowTitle("Cambiar perfil")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Seleccione el perfil que desea abrir."))
        self.profiles = QListWidget()
        self.profiles.setAccessibleName("Perfiles disponibles")
        layout.addWidget(self.profiles, 1)
        self.active_label = QLabel("")
        self.active_label.setObjectName("contextLabel")
        layout.addWidget(self.active_label)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("Abrir")
        cancel_button = QPushButton("Cancelar")
        buttons.addWidget(self.open_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)
        self.open_button.clicked.connect(self._open)
        cancel_button.clicked.connect(self.reject)
        self.profiles.itemDoubleClicked.connect(lambda _item: self._open())
        self._refresh()

    def _refresh(self) -> None:
        from gipler.profile import list_profiles

        self.profiles.clear()
        active_id = self.window.profile.id if self.window.profile else None
        active_name = self.window.profile.name if self.window.profile else None
        for profile in list_profiles():
            label = (
                f"{profile.name} (activo)"
                if profile.id == active_id
                else profile.name
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, profile.id)
            if profile.id == active_id:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.profiles.addItem(item)
        self.active_label.setText(
            f"Perfil activo: {active_name}" if active_name else "Perfil activo: ninguno"
        )
        if self.profiles.count():
            self.profiles.setCurrentRow(0)

    def _open(self) -> None:
        item = self.profiles.currentItem()
        if item is None:
            return
        profile_id = item.data(Qt.UserRole)
        active_id = self.window.profile.id if self.window.profile else None
        if profile_id == active_id:
            self.reject()
            return
        self.profile_id = profile_id
        self.accept()


class ProfileAdminDialog(QDialog):
    """Administración del perfil activo: identidad, directorio y referencias."""

    def __init__(self, window: "GiplerWindow"):
        super().__init__(window)
        self.window = window
        self.profile = window.profile
        self.setWindowTitle("Administrar perfil")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self._apply_section_style()

        perfil_section = self._section("Perfil")
        self.name_label = QLabel(self.profile.name)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        perfil_section.layout().addWidget(self.name_label)
        rename_button = QPushButton("Renombrar…")
        rename_button.clicked.connect(self._rename)
        perfil_section.layout().addWidget(rename_button, 0, Qt.AlignLeft)
        layout.addWidget(perfil_section)

        work_section = self._section("Directorio de trabajo")
        self.work_label = QLabel(self.profile.work_dir)
        self.work_label.setWordWrap(True)
        self.work_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        work_section.layout().addWidget(self.work_label)
        change_button = QPushButton("Cambiar…")
        change_button.clicked.connect(self._change_work_dir)
        work_section.layout().addWidget(change_button, 0, Qt.AlignLeft)
        layout.addWidget(work_section)

        refs_section = self._section("Directorios de referencia")
        self.refs_list = QListWidget()
        self.refs_list.setAccessibleName("Referencias configuradas")
        refs_section.layout().addWidget(self.refs_list, 1)
        refs_buttons = QHBoxLayout()
        add_button = QPushButton("Agregar…")
        manage_button = QPushButton("Administrar…")
        add_button.clicked.connect(self._add_source)
        manage_button.clicked.connect(self._manage_sources)
        refs_buttons.addWidget(add_button)
        refs_buttons.addWidget(manage_button)
        refs_buttons.addStretch(1)
        refs_section.layout().addLayout(refs_buttons)
        layout.addWidget(refs_section, 1)

        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)

        self._refresh()

    def _apply_section_style(self) -> None:
        from gipler.gui.theme import PALETTES, load_preference

        p = PALETTES.get(load_preference(), PALETTES["oscuro"])
        self.setStyleSheet(
            f"QFrame#adminSection {{ background: {p['panel2']}; "
            f"border: 1px solid {p['borde']}; border-radius: 10px; }}"
        )

    def _section(self, title: str) -> QFrame:
        section = QFrame()
        section.setObjectName("adminSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        section_layout.addWidget(title_label)
        return section

    def _refresh(self) -> None:
        self.profile = self.window.profile
        self.name_label.setText(self.profile.name)
        self.work_label.setText(self.profile.work_dir)
        self._refill_refs()

    def _refill_refs(self) -> None:
        self.refs_list.clear()
        for source in sorted(self.window.profile.sources, key=lambda item: item.order):
            label = source.name if source.enabled else f"{source.name} (desactivada)"
            if source.kind == "reference_directory":
                label += (
                    f" — línea de base: {source.baseline.established_at}"
                    if source.baseline is not None
                    else " — sin línea de base"
                )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, source.id)
            self.refs_list.addItem(item)

    def _rename(self) -> None:
        self.window._rename_active_profile()
        self._refresh()

    def _change_work_dir(self) -> None:
        self.window._change_profile_work_dir()
        self._refresh()

    def _add_source(self) -> None:
        source_id = self.window._configure_source(self, None)
        if source_id is None:
            return
        self._save_and_refresh()

    def _manage_sources(self) -> None:
        self.window._manage_sources()
        self._refresh()

    def _save_and_refresh(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from gipler.profile import ProfileError, load_profile, save_profile

        try:
            save_profile(self.window.profile)
        except (ProfileError, OSError) as exc:
            self.window.profile = load_profile(self.window.profile.id)
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return
        self._refresh()
        self.window.reanalyze()


class GiplerWindow(QMainWindow):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        from gipler.profile_analysis import analyze_profile

        self.profile_analysis = analyze_profile(profile)
        self.rows = [
            row
            for source_rows in self.profile_analysis.rows_by_source.values()
            for row in source_rows
        ]
        self.meta = {
            "dev": profile.work_dir,
            **{
                source.id: (
                    self.profile_analysis.comparison_roots.get(source.id)
                    or self.profile_analysis.destination_roots.get(source.id, "")
                )
                for source in profile.sources
            },
        }
        self.snapshot = self.profile_analysis.snapshot
        sources = sorted(profile.sources, key=lambda source: source.order)
        self._destination = next(
            (source.id for source in sources if source.enabled), "sin determinar"
        )
        from gipler.gui.selection import SelectionController
        self.selection_ctrl = SelectionController()
        self._eligible_copy_keys: set[tuple[str, str]] | None = None
        self.ops_cache: list = []
        # Identidad de la revisión: la autorización queda ligada al conjunto
        # exacto de operaciones revisado. Una revisión nueva la invalida.
        self._prepared_token: object | None = None
        self._authorized_token: object | None = None
        self.is_executing = False
        self._copy_thread = None
        self._copy_worker = None
        self._profile_admin_pages: dict[str, QWidget] = {}
        self.git_bars = {}
        self._active_git_bar = None
        self._view_mode = "todos"
        self._comparison_axis_b = "todos"
        self.git_tree_model = None
        self._git_files = {}
        self._git_filter = None
        self._git_commit_selection = set()
        self._build_ui()
        self._build_models()
        self._sync_git_bars()
        self._apply_initial_theme()
        self._connect_sync()
        self.apply_filters()
        self._update_counter()
        self._update_summary()
        self.expand_changes()

    # -- modelos --------------------------------------------------------
    def _build_models(self) -> None:
        from gipler.gui.comparison_view import DEV_HEADERS, REPO_HEADERS, PanelProxy

        self.tree_model = ComparisonTreeModel(self.rows, self._destination)
        self.tree_model.checked_keys = self.selection_ctrl.keys
        self.tree_model.copy_selection_changed.connect(
            self._on_tree_copy_selection_changed
        )
        self.proxy = PanelProxy(DEV_HEADERS)
        self.repo_proxy = PanelProxy(REPO_HEADERS)
        self.proxy.physical_side = "dev"
        self.proxy.dev_root = self.meta.get("dev", "")
        self.repo_proxy.physical_side = "repo"
        self.repo_proxy.dev_root = self.meta.get("dev", "")
        self.repo_proxy.repo_root = self._repo_root_for(self._destination)
        for p in (self.proxy, self.repo_proxy):
            p.setSourceModel(self.tree_model)
            p.sort(0, Qt.AscendingOrder)
        self.dev_panel.set_model(self.proxy)
        self.dev_panel.set_empty_message("")
        self.dest_panel.set_model(self.repo_proxy)

    def _connect_sync(self):
        self.dev_panel.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.dest_panel.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.dev_panel.tree.doubleClicked.connect(self._on_double_clicked)
        self.dest_panel.tree.doubleClicked.connect(self._on_double_clicked)
        self.dev_panel.exclude_requested.connect(lambda p: self.exclude_path(p, self._path_is_dir(p)))
        self.dest_panel.exclude_requested.connect(lambda p: self.exclude_path(p, self._path_is_dir(p)))

    def _path_is_dir(self, rel: str) -> bool:
        paths = {n.path for n in self.tree_model.file_nodes()}
        if rel in paths:
            # ¿Es hoja con row (archivo) o directorio con hijos?
            return any(p.startswith(rel + "/") for p in paths)
        return True

    # -- navegación sincronizada -----------------------------------------
    def _sync_navigate(self, index) -> None:
        if not index.isValid():
            return
        for panel in (self.dev_panel, self.dest_panel):
            panel.tree.setRootIndex(index)

    def _sync_navigate_from(self, source_panel, proxy_index) -> None:
        """Navega ambos paneles a la carpeta del índice proxy dado
        (los proxies de Dev y Repo son instancias distintas)."""
        if not proxy_index.isValid():
            return
        source_proxy = self.proxy if source_panel is self.dev_panel else self.repo_proxy
        src_idx = source_proxy.mapToSource(proxy_index)
        for panel, prox in ((self.dev_panel, self.proxy), (self.dest_panel, self.repo_proxy)):
            panel.tree.setRootIndex(prox.mapFromSource(src_idx))

    def _on_selection_changed(self, selected, deselected) -> None:
        from PySide6.QtCore import QItemSelectionModel

        if not selected:
            return
        idx = selected.indexes()[0]
        if self._view_mode == "git":
            if idx.model() is self.repo_proxy and self.git_tree_model is not None:
                node = self.git_tree_model.node_at(self.repo_proxy.mapToSource(idx))
                if node is not None and node.row is not None:
                    self.inicio_panel.inspect_row(node.row)
            return
        # idx es un índice proxy del panel que emitió; traducir a la
        # fuente común y re-mapear a cada proxy (Dev y Repo son
        # instancias distintas desde las cabeceras por panel).
        if idx.model() is self.proxy:
            src_idx = self.proxy.mapToSource(idx)
        elif idx.model() is self.repo_proxy:
            src_idx = self.repo_proxy.mapToSource(idx)
        else:
            return
        for panel, prox in ((self.dev_panel, self.proxy), (self.dest_panel, self.repo_proxy)):
            selex = panel.tree.selectionModel()
            if selex is None:
                continue
            target = prox.mapFromSource(src_idx)
            if target is None or not target.isValid():
                continue
            if selex.currentIndex() != target:
                selex.setCurrentIndex(target, QItemSelectionModel.SelectionFlag.Current)
            selex.select(target, QItemSelectionModel.SelectionFlag.Select)
        row = self._current_row(idx)
        if row is not None:
            self.inicio_panel.inspect_row(row)

    def _repo_root_for(self, destination: str) -> str:
        m = self.meta or {}
        if self.profile_analysis is not None:
            return (
                self.profile_analysis.comparison_roots.get(destination)
                or self.profile_analysis.destination_roots.get(destination, "")
            )
        if destination == "principal":
            return m.get("principal", "")
        if destination == "addons":
            return m.get("addons", "")
        return ""

    def _current_row(self, proxy_index):
        from gipler.report import Row as RowCls

        if not proxy_index.isValid():
            return None
        if proxy_index.model() not in (self.proxy, self.repo_proxy):
            return None
        prox = self.repo_proxy if proxy_index.model() is self.repo_proxy else self.proxy
        node = self.tree_model.node_at(prox.mapToSource(proxy_index))
        return node.row if node else None

    def _on_double_clicked(self, index) -> None:
        if self._view_mode == "git":
            if index.model() is self.repo_proxy:
                self.dest_panel.tree.setRootIndex(index)
            return
        node = self._source_node(index)
        if node is None:
            return
        if node.is_dir and node.children:
            sender = self.sender()
            src_panel = self.dev_panel if sender == self.dev_panel.tree else self.dest_panel
            source_proxy = self.proxy if src_panel is self.dev_panel else self.repo_proxy
            if index.model() is self.dest_panel.tree.model():
                source_proxy = self.repo_proxy
            elif self.dev_panel.tree.model() is not None:
                source_proxy = self.proxy
            src_idx = source_proxy.mapToSource(index)
            for panel, prox in ((self.dev_panel, self.proxy), (self.dest_panel, self.repo_proxy)):
                panel.tree.setRootIndex(prox.mapFromSource(src_idx))
        else:
            self.open_comparison(node.row)

    def open_comparison(self, row) -> None:
        """Abre una ventana independiente de comparación del archivo."""
        from gipler.gui.comparison_window import ComparisonWindow

        win = ComparisonWindow(
            row,
            self.meta.get("dev", ""),
            self._repo_root_for(row.destination),
            parent=self,
        )
        win.show()
        win.raise_()
        win.activateWindow()

    def _source_node(self, proxy_index):
        if not proxy_index.isValid() or proxy_index.model() not in (self.proxy, self.repo_proxy):
            return None
        prox = self.repo_proxy if proxy_index.model() is self.repo_proxy else self.proxy
        src_idx = prox.mapToSource(proxy_index)
        return self.tree_model.node_at(src_idx)

    def go_up(self) -> None:
        for panel in (self.dev_panel, self.dest_panel):
            panel.tree.setRootIndex(panel.tree.rootIndex().parent() if panel.tree.rootIndex().isValid() else panel.tree.rootIndex())

    # -- filtros -----------------------------------------------------------
    def _on_axis_a_index_changed(self, index: int) -> None:
        mode = self.axis_a_box.itemData(index) or self.axis_a_box.itemText(index)
        if mode == self._view_mode:
            return
        previous = self._view_mode
        if previous != "git":
            self._comparison_axis_b = self.axis_b_box.currentData() or "todos"
        self._view_mode = mode
        if mode == "git":
            if not self._enter_git_view():
                self._view_mode = previous
                self.axis_a_box.blockSignals(True)
                self.axis_a_box.setCurrentIndex(
                    self.axis_a_box.findData(previous)
                )
                self.axis_a_box.blockSignals(False)
                return
        else:
            self._exit_git_view()
        self._set_axis_b_options(mode)
        self.apply_filters()

    def _on_axis_b_index_changed(self, _index: int) -> None:
        if self._view_mode == "git":
            self._git_filter = self.axis_b_box.currentData()
        else:
            self._comparison_axis_b = self.axis_b_box.currentData() or "todos"
        self.apply_filters()

    def _populate_axis_b_options(self) -> None:
        self.axis_b_box.addItems(AXIS_B)
        for index in range(self.axis_b_box.count()):
            key = self.axis_b_box.itemText(index)
            self.axis_b_box.setItemText(index, AXIS_B_LABELS.get(key, key))
            self.axis_b_box.setItemData(index, key, Qt.UserRole)

    def _set_axis_b_options(self, mode: str) -> None:
        self.axis_b_box.blockSignals(True)
        self.axis_b_box.clear()
        if mode == "git":
            for key in GIT_AXIS_B:
                self.axis_b_box.addItem(GIT_AXIS_B_LABELS[key], key)
            selected = self._git_filter or "unstaged_changes"
        else:
            self._populate_axis_b_options()
            selected = self._comparison_axis_b
        selected_index = self.axis_b_box.findData(selected)
        self.axis_b_box.setCurrentIndex(
            selected_index if selected_index >= 0 else 0
        )
        self.axis_b_box.blockSignals(False)

    def _toggle_search(self, visible: bool) -> None:
        self.search_edit.setVisible(visible)
        if visible:
            self.search_edit.setFocus()
        else:
            self.search_edit.clear()

    def _git_rows(self, files, destination: str):
        from types import SimpleNamespace

        rows = []
        for item in files:
            statuses = item.statuses
            if "untracked" in statuses:
                axis_a = "new_in_dev"
            elif "modified_unstaged" in statuses:
                axis_a = "modified_in_dev"
            elif "conflicts" in statuses:
                axis_a = "ambiguous"
            else:
                axis_a = "identical"
            rows.append(
                SimpleNamespace(
                    path=item.path,
                    destination=destination,
                    axis_a=axis_a,
                    axis_b=item.status_label,
                    incidences=[],
                    owner="git",
                    git_statuses=statuses,
                    git_change="",
                    git_stage="",
                )
            )
        return rows

    def _enter_git_view(self) -> bool:
        root = self._repo_root_for(self._destination)
        if not root or not os.path.lexists(os.path.join(root, ".git")):
            self.status.showMessage(
                "La referencia activa no es un repositorio Git."
            )
            return False
        try:
            from gipler.git_integration import git_status_files

            files = git_status_files(root)
        except Exception as exc:
            self.status.showMessage(
                f"No se pudo obtener el estado Git: {exc}"
            )
            return False
        rows = self._git_rows(files, self._destination)
        self._git_files = {item.path: item for item in files}
        self.git_tree_model = ComparisonTreeModel(rows, destination=None)
        self.git_tree_model.semantic_theme = self.tree_model.semantic_theme
        self.git_tree_model.commit_mode = True
        eligible = {
            path
            for path, item in self._git_files.items()
            if item.statuses & {"modified_unstaged", "untracked"}
        }
        self.git_tree_model.set_commit_eligible(eligible)
        if self._git_commit_selection:
            self.git_tree_model.add_commit_paths(
                self._git_commit_selection & eligible
            )
        self.git_tree_model.commit_selection_changed.connect(
            self._on_commit_selection_changed
        )
        self.repo_proxy.git_mode = True
        self.repo_proxy.setSourceModel(self.git_tree_model)
        self.repo_proxy.dev_root = ""
        self.repo_proxy.repo_root = root
        self.repo_proxy.physical_side = "repo"
        self.dev_panel.clear()
        self.dest_panel.set_model(self.repo_proxy)
        self.dest_panel.set_commit_mode(True)
        self.dest_panel.reset_commit_form()
        bar = self.git_bars.get(self._destination)
        if bar is not None:
            bar.collapse_commit()
        self.search_edit.setEnabled(False)
        self.search_button.setEnabled(False)
        self.search_edit.setVisible(False)
        self._update_commit_ui()
        self._refresh_active_git_bar()
        self.status.showMessage(
            "Vista Git: repositorio de la referencia activa (solo lectura)."
        )
        return True

    def _refresh_git_eligibility(self, files=None) -> None:
        """Relee estados Git y poda la selección que dejó de ser elegible."""
        if self._view_mode != "git" or self.git_tree_model is None:
            return
        if files is None:
            root = self._repo_root_for(self._destination)
            if not root:
                return
            try:
                from gipler.git_integration import git_status_files

                files = git_status_files(root)
            except Exception:
                return
        self._git_files = {item.path: item for item in files}
        eligible = {
            path
            for path, item in self._git_files.items()
            if item.statuses & {"modified_unstaged", "untracked"}
        }
        selected = set(self.git_tree_model.commit_selected)
        self.git_tree_model.set_commit_eligible(eligible)
        kept = selected & eligible
        if kept:
            self.git_tree_model.add_commit_paths(kept)
        self._update_commit_ui()

    def _exit_git_view(self) -> None:
        if self.git_tree_model is not None:
            self._git_filter = self.axis_b_box.currentData()
            self._git_commit_selection = set(
                self.git_tree_model.commit_selected
            )
        self.repo_proxy.git_mode = False
        self.repo_proxy.setSourceModel(self.tree_model)
        self.repo_proxy.dev_root = self.meta.get("dev", "")
        self.repo_proxy.repo_root = self._repo_root_for(self._destination)
        self.dev_panel.set_model(self.proxy)
        self.dev_panel.set_empty_message("")
        self.dest_panel.set_model(self.repo_proxy)
        self.dest_panel.set_commit_mode(False)
        self.search_edit.setEnabled(True)
        self.search_button.setEnabled(True)
        self.search_edit.setVisible(self.search_button.isChecked())
        self.git_tree_model = None
        self._git_files = {}
        self._refresh_active_git_bar()

    def _visible_git_paths(self) -> set[str]:
        if self._view_mode != "git" or self.git_tree_model is None:
            return set()
        paths: set[str] = set()
        proxy = self.repo_proxy
        source = proxy.sourceModel()

        def walk(parent) -> None:
            for row in range(proxy.rowCount(parent)):
                index = proxy.index(row, 0, parent)
                node = source.node_at(proxy.mapToSource(index))
                if node is not None and node.row is not None:
                    paths.add(node.path)
                walk(index)

        walk(QModelIndex())
        return paths

    def _visible_eligible_paths(self) -> set[str]:
        if self.git_tree_model is None:
            return set()
        return {
            path
            for path in self._visible_git_paths()
            if path in self.git_tree_model.commit_eligible
        }

    def _update_commit_ui(self) -> None:
        if self._view_mode != "git" or self.git_tree_model is None:
            return
        selected = set(self.git_tree_model.commit_selected)
        visible_eligible = self._visible_eligible_paths()
        self.dest_panel.set_commit_count(
            f"{len(selected)} archivos seleccionados" if selected else ""
        )
        bar = self.git_bars.get(self._destination)
        ready = bool(
            bar is not None and bar.available and not bar.controller.busy
        )
        conflicts = bool(
            bar is not None and bar.status is not None and bar.status.unmerged
        )
        self.dest_panel.set_commit_enabled(
            bool(selected) and ready and not conflicts
        )
        self.dest_panel.set_select_all_state(visible_eligible, selected)
        if conflicts:
            self.dest_panel.set_commit_warning(CONFLICT_COMMIT_BLOCK)
        elif self.dest_panel.commit_warning.text() == CONFLICT_COMMIT_BLOCK:
            self.dest_panel.set_commit_warning("")

    def _on_commit_selection_changed(self, _paths) -> None:
        self._update_commit_ui()

    def _on_select_all_commit_changed(self, state: int) -> None:
        if self._view_mode != "git" or self.git_tree_model is None:
            return
        visible_eligible = self._visible_eligible_paths()
        if state == 2:  # Qt.Checked
            self.git_tree_model.add_commit_paths(visible_eligible)
        else:
            self.git_tree_model.remove_commit_paths(visible_eligible)
        self._update_commit_ui()

    def _update_commit_warnings(self) -> None:
        if self.git_tree_model is None:
            return
        selected = set(self.git_tree_model.commit_selected)
        staged_outside = [
            path
            for path, item in self._git_files.items()
            if item.staged and path not in selected
        ]
        partial = [
            path
            for path in selected
            if self._git_files.get(path) is not None
            and self._git_files[path].staged
            and self._git_files[path].unstaged
        ]
        warnings = []
        if staged_outside:
            warnings.append(
                f"Hay {len(staged_outside)} archivos preparados fuera de la "
                "selección. No se incluirán en el commit."
            )
        if partial:
            warnings.append(
                "Los archivos con cambios preparados y sin preparar se "
                "confirmarán con su contenido completo."
            )
        self.dest_panel.set_commit_warning("\n".join(warnings))
        self.dest_panel.set_include_staged_visible(bool(staged_outside))

    def _on_commit_requested(self) -> None:
        if self._view_mode != "git" or self.git_tree_model is None:
            return
        if not self.git_tree_model.commit_selected:
            return
        bar = self.git_bars.get(self._destination)
        if bar is not None and bar.status is not None and bar.status.unmerged:
            self.dest_panel.set_commit_warning(CONFLICT_COMMIT_BLOCK)
            return
        self.dest_panel.set_commit_message_visible(True)
        self.dest_panel.set_commit_error("")
        self.dest_panel.focus_commit_message()
        self._update_commit_warnings()

    def _on_commit_confirmed(self, message: str) -> None:
        if self._view_mode != "git" or self.git_tree_model is None:
            return
        clean = (message or "").strip()
        if not clean:
            self.dest_panel.set_commit_error(
                "El mensaje del commit no puede estar vacío."
            )
            return
        selected = sorted(self.git_tree_model.commit_selected)
        if not selected:
            self.dest_panel.set_commit_error(
                "No hay archivos seleccionados para el commit."
            )
            return
        bar = self.git_bars.get(self._destination)
        if bar is None:
            return
        if bar.controller.busy:
            self.dest_panel.set_commit_warning(
                "Espere a que termine la operación Git en curso."
            )
            return
        root = self._repo_root_for(self._destination)
        if not root:
            self.dest_panel.set_commit_error(
                "No se pudo revalidar el repositorio Git de la referencia."
            )
            return
        try:
            from gipler.git_integration import git_status_files

            files = git_status_files(root)
        except Exception as exc:
            self.dest_panel.set_commit_error(
                f"No se pudo revalidar el estado Git: {exc}"
            )
            return
        self._refresh_git_eligibility(files)
        if any("conflicts" in item.statuses for item in files):
            self.dest_panel.set_commit_error(CONFLICT_COMMIT_BLOCK)
            return
        eligible = {
            item.path
            for item in files
            if item.statuses & {"modified_unstaged", "untracked"}
        }
        if any(path not in eligible for path in selected):
            self.dest_panel.set_commit_error(
                "La selección cambió: hay archivos que ya no son elegibles. "
                "No se confirmó ningún archivo."
            )
            return
        include = self.dest_panel.commit_include_staged_checked()
        self.dest_panel.set_commit_enabled(False)
        bar.controller.commit_selected(
            clean, selected, include_staged_outside=include
        )

    def _on_commit_cancelled(self) -> None:
        self.dest_panel.reset_commit_form()

    def _on_git_commit_finished(self, result) -> None:
        if result.kind != "commit_selected":
            return
        if result.ok:
            self._git_commit_selection = set()
            self.dest_panel.reset_commit_form()
            self._enter_git_view()
            self._refresh_active_git_bar()
            if self._active_git_bar is not None:
                self._active_git_bar.refresh_status()
            self.status.showMessage(result.message)
        else:
            self.dest_panel.set_commit_error(result.message)
            self._refresh_git_eligibility()

    def apply_filters(self) -> None:
        a = self.axis_a_box.currentData() or self.axis_a_box.currentText()
        b = self.axis_b_box.currentData() or self.axis_b_box.currentText()
        inc = b == "incidencias"
        txt = self.search_edit.text()
        if a == "git":
            self.repo_proxy.set_criteria(
                axis_a=None,
                axis_b=None if b in ("todos", "incidencias") else b,
                incidences=False,
                search="",
                owner="",
                exclude_identical=False,
            )
            self.expand_changes()
            self._update_counter()
            self._update_commit_ui()
            return
        differences_only = a == "diferencias"
        self.proxy.git_mode = False
        self.repo_proxy.git_mode = False
        for p in (self.proxy, self.repo_proxy):
            p.set_criteria(
                axis_a=None if a == "todos" or differences_only else a,
                axis_b=None if b in ("todos", "incidencias") else b,
                incidences=inc,
                search=txt,
                owner="",
                exclude_identical=differences_only,
            )
        self.expand_changes()
        self._update_counter()

    def _update_counter(self) -> None:
        if self._view_mode == "git":
            n = visible_file_count(self.repo_proxy)
            proxy = self.repo_proxy
            selected_paths = (
                self.git_tree_model.commit_selected
                if self.git_tree_model is not None
                else set()
            )
            self.dest_panel.set_empty_message(
                "No hay archivos que coincidan con este filtro"
                if n == 0
                else ""
            )
            self.dev_panel.set_empty_message("")
        else:
            n = visible_file_count(self.proxy)
            proxy = self.proxy
            selected_keys = self.selection_ctrl.keys
            self.dest_panel.set_empty_message("")
        source = proxy.sourceModel()
        selected_visible = 0

        def count_selected(parent=QModelIndex()):
            nonlocal selected_visible
            for row_index in range(proxy.rowCount(parent)):
                index = proxy.index(row_index, 0, parent)
                source_index = proxy.mapToSource(index)
                node = source.node_at(source_index)
                if node.row is not None:
                    if self._view_mode == "git":
                        selected_visible += node.row.path in selected_paths
                    else:
                        key = selection_key_for(node.row)
                        selected_visible += key is not None and key in selected_keys
                count_selected(index)

        count_selected()
        text = f"{n} visibles · {selected_visible} seleccionados"
        tooltip = "Elementos visibles y seleccionados en la vista actual"
        if self._view_mode != "git":
            self._sync_context_text = text
            self._sync_context_tooltip = tooltip
            self.context_label.setText(text)
            self.context_label.setToolTip(tooltip)
        selected = len(self.selection_ctrl)
        self.status.showMessage(f"Vista: {self._destination} · visibles: {n} archivos · seleccionados: {selected}")

    def set_destination(self, dest: str) -> None:
        valid = set(self.repo_buttons) | {"sin determinar"}
        if dest not in valid:
            return
        if dest != self._destination:
            self._git_filter = None
            self._git_commit_selection = set()
        self._destination = dest
        self.repo_proxy.repo_root = self._repo_root_for(dest)
        self.tree_model.set_rows(self.rows, dest)
        self.proxy.apply()
        self.repo_proxy.apply()
        self._update_counter()
        self._update_summary()
        self.expand_changes()
        self.dest_panel.set_title(
            self._reference_title(dest),
            tooltip=self._repo_root_for(dest),
        )
        self._refresh_active_git_bar()
        self._update_git_option()
        if self._view_mode == "git":
            if not self._enter_git_view():
                self._view_mode = "todos"
                self._set_axis_b_options("todos")
                self.axis_a_box.blockSignals(True)
                self.axis_a_box.setCurrentIndex(
                    self.axis_a_box.findData("todos")
                )
                self.axis_a_box.blockSignals(False)
            self.apply_filters()

    # -- Git contextual -------------------------------------------------
    def _reference_title(self, destination: str) -> str:
        root = self._repo_root_for(destination)
        if root:
            name = os.path.basename(os.path.normpath(root))
            return name or root
        return "Repositorio"

    def _git_destinations(self) -> dict[str, tuple[str, bool]]:
        if self.profile is not None:
            return {
                source.id: (self._repo_root_for(source.id), source.enabled)
                for source in sorted(self.profile.sources, key=lambda item: item.order)
            }
        return {
            "principal": (self._repo_root_for("principal"), True),
            "addons": (self._repo_root_for("addons"), True),
        }

    def _sync_git_bars(self) -> None:
        """Create/update one independent header control per physical reference."""
        if not hasattr(self, "git_bar_stack"):
            return
        from gipler.gui.git_bar import GitBar

        wanted = self._git_destinations()
        for destination in list(self.git_bars):
            if destination in wanted:
                continue
            bar = self.git_bars.pop(destination)
            if self._active_git_bar is bar:
                self._active_git_bar = None
            bar.deactivate()
            bar.controller.shutdown()
            self.git_bar_stack.removeWidget(bar)
            bar.deleteLater()
        for destination, (root, enabled) in wanted.items():
            bar = self.git_bars.get(destination)
            if bar is None:
                bar = GitBar(root, self, context_label=self.context_label)
                bar.message.connect(self.status.showMessage)
                bar.repository_changed.connect(self._on_git_repository_changed)
                bar.controller.operation_finished.connect(
                    self._on_git_commit_finished
                )
                bar.status_changed.connect(
                    lambda status, dest=destination: self._on_git_status_changed(
                        dest, status
                    )
                )
                self.git_bars[destination] = bar
                self.git_bar_stack.addWidget(bar)
            else:
                bar.set_repository(root)
            bar.setEnabled(enabled)
            if not enabled:
                bar.deactivate()
                bar.setVisible(False)
        self._refresh_active_git_bar()

    def _on_git_status_changed(self, destination: str, status) -> None:
        if destination == self._destination:
            self._refresh_active_git_bar()
            self._update_git_option(status)
            self._refresh_git_eligibility()
            self._update_commit_ui()

    def _update_git_option(self, status=None) -> None:
        root = self._repo_root_for(self._destination)
        available = bool(root and os.path.lexists(os.path.join(root, ".git")))
        index = self.axis_a_box.findData("git")
        if index >= 0:
            self.axis_a_box.model().item(index).setEnabled(available)
        if not available and self._view_mode == "git":
            self._view_mode = "todos"
            self._exit_git_view()
            self._set_axis_b_options("todos")
            self.axis_a_box.blockSignals(True)
            self.axis_a_box.setCurrentIndex(
                self.axis_a_box.findData("todos")
            )
            self.axis_a_box.blockSignals(False)
            self.apply_filters()
            self.status.showMessage(
                "La referencia activa no tiene un repositorio Git disponible."
            )

    def _refresh_active_git_bar(self) -> None:
        if not hasattr(self, "git_bar_stack"):
            return
        if hasattr(self, "sync_toolbar_controls"):
            show_sync_tools = self._view_mode != "git"
            self.contextual_spacer.setVisible(True)
            self.sync_toolbar_controls.setVisible(show_sync_tools)
        on_compare = self.stacked.currentWidget() is getattr(
            self, "compare_page", None
        )
        if self._view_mode != "git" or not on_compare:
            self._deactivate_git_bar()
            self.git_bar_stack.setVisible(False)
            self._restore_sync_context()
            return
        bar = self.git_bars.get(self._destination)
        if bar is None or not bar.isEnabled():
            self._deactivate_git_bar()
            self.git_bar_stack.setVisible(False)
            self._restore_sync_context()
            return
        if self._active_git_bar is not bar:
            self._deactivate_git_bar()
            self._active_git_bar = bar
            bar.activate()
        bar.refresh_context()
        self.git_bar_stack.setCurrentWidget(bar)
        self.git_bar_stack.setVisible(bar.available and bar.isEnabled())

    def _restore_sync_context(self) -> None:
        self.context_label.setText(
            getattr(self, "_sync_context_text", "0 visibles · 0 seleccionados")
        )
        self.context_label.setToolTip(getattr(self, "_sync_context_tooltip", ""))

    def _deactivate_git_bar(self) -> None:
        if self._active_git_bar is not None:
            self._active_git_bar.deactivate()
            self._active_git_bar = None

    def _on_git_repository_changed(self, repository: str) -> None:
        self.status.showMessage(
            "Repositorio Git actualizado; recalculando la comparación…"
        )
        self.reanalyze()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        app = QApplication.instance()
        if app is not None:
            # Identidad de escritorio: asocia la ventana con gipler.desktop
            # para que el panel muestre el icono en taskbar y Alt+Tab.
            app.setApplicationName("Gipler")
            app.setDesktopFileName("gipler")
        self.setWindowTitle("Gipler")
        self.setWindowIcon(QIcon(_app_icon()))
        self.resize(1440, 900)
        self.statusBar().showMessage("Análisis no ejecutado (Fase 1)")

        # Barra superior: pestañas (Inicio + destinos) y, a la derecha,
        # el menú de herramientas (no son espacios de trabajo).
        bar = QToolBar("Principal", self)
        bar.setObjectName("navigationToolbar")
        self.addToolBar(bar)
        self.nav_toolbar = bar
        self.tools_menu = self.menuBar().addMenu("Herramientas")
        act_update = QAction("Actualizar", self)
        act_update.triggered.connect(self.reanalyze)
        self.tools_menu.addAction(act_update)
        theme_menu = self.tools_menu.addMenu("Apariencia")
        for name in ("oscuro", "claro"):
            act = QAction("Oscuro grafito" if name == "oscuro" else "Claro", self)
            act.triggered.connect(lambda _c=False, t=name: self.apply_theme(t))
            theme_menu.addAction(act)
        self.repo_buttons: dict[str, QPushButton] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.nav_group = group
        # Inicio es la primera pestaña de control; el resto son destinos.
        start = EditorialNavButton("Inicio")
        start.setCheckable(True)
        start.clicked.connect(self._show_inicio)
        self.nav_buttons["inicio"] = start
        group.addButton(start)
        bar.addWidget(start)
        destinations = [
            (source.id, source.name if source.enabled else f"{source.name} (desactivada)")
            for source in sorted(self.profile.sources, key=lambda source: source.order)
        ]
        for name, label in destinations:
            b = EditorialNavButton(label)
            b.setCheckable(True)
            b.setChecked(name == self._destination)
            source = self.profile.source(name)
            b.setEnabled(source.enabled if source is not None else True)
            b.clicked.connect(lambda _checked=False, dest=name: self._on_repo(button=dest))
            self.repo_buttons[name] = b
            group.addButton(b)
            bar.addWidget(b)
        self.admin_buttons: dict[str, QPushButton] = {}
        self._admin_nav_actions = []
        for key, label in (
            ("excluidos", "Excluidos"),
            ("indeterminados", "Indeterminados"),
        ):
            button = EditorialNavButton(label)
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, page_key=key: self._show_profile_admin(page_key)
            )
            self.admin_buttons[key] = button
            group.addButton(button)
            self._admin_nav_actions.append(bar.addWidget(button))
        profile_menu = self.menuBar().addMenu("Perfiles")
        active = QAction(f"Activo: {self.profile.name}", self)
        active.setEnabled(False)
        profile_menu.addAction(active)
        profile_menu.addAction("Cambiar perfil…", self._switch_profile)
        profile_menu.addAction("Administrar perfil…", self._admin_profile)

        # Barra contextual con la misma composición
        # visual que la barra de contexto de Inicio (ver SummaryPanel).
        filter_row = QFrame()
        filter_row.setObjectName("referenceControls")
        filter_row.setFrameShape(QFrame.Shape.NoFrame)
        fr = QHBoxLayout(filter_row)
        fr.setContentsMargins(10, 8, 10, 8)
        fr.setSpacing(12)
        self.axis_a_box = QComboBox()
        self.axis_a_box.addItems(AXIS_A)
        for index in range(self.axis_a_box.count()):
            self.axis_a_box.setItemData(
                index, self.axis_a_box.itemText(index), Qt.UserRole
            )
        diferencias_index = self.axis_a_box.findText("diferencias")
        self.axis_a_box.setItemText(diferencias_index, "Diferencias")
        self.axis_a_box.setItemData(diferencias_index, "diferencias", Qt.UserRole)
        git_index = self.axis_a_box.findText("git")
        self.axis_a_box.setItemText(git_index, "Git")
        self.axis_a_box.setItemData(git_index, "git", Qt.UserRole)
        if self.profile is not None:
            self.axis_a_box.setCurrentText("Diferencias")
        self.axis_a_box.setToolTip(
            "Diferencias oculta archivos idénticos sin eliminarlos del análisis. "
            "Seleccione «identical» o «todos» para consultarlos."
        )
        self.axis_b_box = QComboBox()
        self._populate_axis_b_options()
        self.axis_b_box.setAccessibleName("Filtro de archivos")
        self.axis_b_box.setToolTip("Filtrar los archivos por estado")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por nombre o ruta…")
        self.search_edit.setFixedWidth(180)
        self.search_edit.setVisible(False)
        view_label = QLabel("Vista")
        view_label.setBuddy(self.axis_a_box)
        view_label.setAccessibleName("Etiqueta de tipo de vista")
        view_label.setObjectName("contextLabel")
        filter_label = QLabel("Filtro")
        filter_label.setBuddy(self.axis_b_box)
        filter_label.setAccessibleName("Etiqueta de filtro de archivos")
        filter_label.setObjectName("contextLabel")
        self.visible_counter = make_context_label("0 visibles · 0 seleccionados")
        self.context_label = self.visible_counter
        self._sync_context_text = self.visible_counter.text()
        self._sync_context_tooltip = (
            "Elementos visibles y seleccionados en la vista actual"
        )
        self.search_button = QToolButton()
        search_icon = QIcon.fromTheme("edit-find")
        if search_icon.isNull():
            self.search_button.setText("Buscar")
        else:
            self.search_button.setIcon(search_icon)
        self.search_button.setCheckable(True)
        self.search_button.setAccessibleName("Mostrar u ocultar búsqueda")
        self.search_button.setToolTip("Buscar por nombre o ruta")
        self.search_button.toggled.connect(self._toggle_search)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_button.setAccessibleName("Actualizar análisis")
        self.refresh_button.setToolTip("Actualizar análisis")
        self.refresh_button.clicked.connect(self.reanalyze)
        fr.addWidget(view_label)
        fr.addWidget(self.axis_a_box)
        fr.addWidget(filter_label)
        fr.addWidget(self.axis_b_box)
        self.filter_bar = filter_row
        self.sync_toolbar_controls = QWidget(filter_row)
        sync_controls_layout = QHBoxLayout(self.sync_toolbar_controls)
        sync_controls_layout.setContentsMargins(0, 0, 0, 0)
        sync_controls_layout.setSpacing(12)
        sync_controls_layout.addWidget(self.search_button)
        sync_controls_layout.addWidget(self.search_edit)
        sync_controls_layout.addWidget(self.refresh_button)
        self.contextual_spacer = QWidget(filter_row)
        self.contextual_spacer.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )

        self.axis_a_box.currentIndexChanged.connect(self._on_axis_a_index_changed)
        self.axis_b_box.currentIndexChanged.connect(self._on_axis_b_index_changed)
        self.search_edit.textChanged.connect(lambda _x: self.apply_filters())

        # Zona principal: QStackedWidget (Inicio | comparación).
        self.stacked = QStackedWidget()
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(21, 9, 21, 9)
        self.inicio_panel = SummaryPanel()
        self.inicio_panel.setMaximumHeight(100000)
        self.inicio_panel.open_requested.connect(self.open_comparison)
        self.inicio_panel.exclude_requested.connect(
            lambda row: self.exclude_path(row.path, False)
        )
        self.inicio_panel.explorer_requested.connect(self._open_relevant_in_explorer)
        self.inicio_panel.copy_selection_changed.connect(
            self._on_home_copy_selection_changed
        )
        self.inicio_panel.assign_requested.connect(self._assign_new_file)
        self.btn_execute = self.inicio_panel.btn_execute
        self.btn_execute.clicked.connect(self._execute_from_panel)
        self.btn_safe = self.inicio_panel.btn_safe
        self.btn_safe.clicked.connect(self.select_safe_visible)
        self.btn_prepare = self.inicio_panel.btn_prepare
        self.btn_prepare.clicked.connect(lambda: self.prepare_operations(show_dialog=True))
        splitter = QSplitter(Qt.Horizontal)
        self.dev_panel = ComparisonPanel("Dev")
        self.dest_panel = ComparisonPanel("Repositorio")
        self.dest_panel.set_reference_mode(True)
        self.git_bar_stack = QStackedWidget()
        self.git_bar_stack.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed
        )
        self.git_bar_stack.setVisible(False)
        self.dest_panel.select_all_commit_changed.connect(
            self._on_select_all_commit_changed
        )
        self.dest_panel.commit_requested.connect(self._on_commit_requested)
        self.dest_panel.commit_confirmed.connect(self._on_commit_confirmed)
        self.dest_panel.commit_cancelled.connect(self._on_commit_cancelled)
        self.dest_panel.set_title(
            self._reference_title(self._destination),
            tooltip=self._repo_root_for(self._destination),
        )
        splitter.addWidget(self.dev_panel)
        splitter.addWidget(self.dest_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter
        central_layout.addWidget(filter_row)
        filter_row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        fr.addWidget(self.contextual_spacer)
        fr.addWidget(self.context_label)
        fr.addWidget(self.sync_toolbar_controls)
        fr.addWidget(self.git_bar_stack)
        central_layout.addWidget(splitter)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        central_layout.setStretch(1, 1)
        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.bottom_splitter.addWidget(central)
        central.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        compare_page = QWidget()
        compare_layout = QVBoxLayout(compare_page)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.addWidget(central)
        self.compare_page = compare_page
        self.stacked.addWidget(self.inicio_panel)
        self.stacked.addWidget(compare_page)
        if self.profile is not None:
            self._refresh_profile_admin_pages()
        self.setCentralWidget(self.stacked)
        # Leyenda cromática compartida (discreta).
        x = 1

        legend = QWidget()
        leg = QHBoxLayout(legend)
        from gipler.gui.theme import PALETTES

        for label, theme_key in (
            ("Nuevo en Dev (verde)", "new_in_dev"),
            ("Modificado (azul)", "modified_in_dev"),
            ("Ambiguo/advertencias (naranja)", "ambiguous"),
            ("Idéntico (gris)", "identical"),
            ("No comparable (violeta)", "not_comparable"),
            ("* sincronizado con diferencia Git", ""),
            ("⌀ diferencia de permisos Dev→repo", ""),
        ):
            lab = QLabel(label)
            leg.addWidget(lab)
        self.statusBar().addPermanentWidget(legend)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Listo")
        self._show_inicio()

    def apply_theme(self, theme: str) -> None:
        from gipler.gui import theme as th

        th.apply_theme(theme)
        self.tree_model.semantic_theme = theme
        if self.git_tree_model is not None:
            self.git_tree_model.semantic_theme = theme
        self.tree_model.dataChanged.emit(self.tree_model.index(0, 0), self.tree_model.index(0, 0))
        self.status.showMessage(f"Tema: {'Oscuro grafito' if theme == 'oscuro' else 'Claro'} (guardado)")

    def _apply_initial_theme(self) -> None:
        from gipler.gui.theme import apply_theme, load_preference
        theme = load_preference()
        apply_theme(theme)
        self.tree_model.semantic_theme = theme

    def exclude_path(self, rel: str, is_dir: bool) -> None:
        """Guarda la exclusión del perfil e invalida la vista con
        el reanálisis existente (no modifica archivos ni Git)."""
        self._invalidate_review()
        affected = selection_keys_for_path(
            self.selection_ctrl.keys, rel, is_dir
        )
        self.selection_ctrl.keys.difference_update(affected)
        from gipler.profile import add_exclusion

        try:
            add_exclusion(
                self.profile.id, rel.rstrip("/") + ("/" if is_dir else "")
            )
        except (OSError, ValueError) as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "No se pudo excluir", str(exc))
            return
        self.reanalyze()

    def _open_relevant_in_explorer(self, row) -> None:
        """Abre el directorio que contiene la copia física relevante."""
        import os
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        dev_path = os.path.join(self.meta.get("dev", ""), row.path)
        repo_root = self._repo_root_for(row.destination)
        repo_path = os.path.join(repo_root, row.path) if repo_root else ""
        if row.axis_a == "missing_in_dev" and repo_path and os.path.lexists(repo_path):
            source_path = repo_path
        elif os.path.lexists(dev_path):
            source_path = dev_path
        elif repo_path and os.path.lexists(repo_path):
            source_path = repo_path
        else:
            self.status.showMessage(f"No se encontró una copia física de: {row.path}")
            return

        directory = source_path if os.path.isdir(source_path) else os.path.dirname(source_path)
        if not directory or not os.path.isdir(directory):
            self.status.showMessage(f"No se encontró el directorio: {directory or source_path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(directory))):
            self.status.showMessage(f"No se pudo abrir el directorio: {directory}")

    def _show_inicio(self) -> None:
        self.stacked.setCurrentWidget(self.inicio_panel)
        # Estado visual coherente desde el arranque: Inicio marcada y
        # destinos desmarcados (index 0 = Inicio).
        if getattr(self, "nav_buttons", None) and "inicio" in self.nav_buttons:
            self.nav_buttons["inicio"].setChecked(True)
        for b in getattr(self, "repo_buttons", {}).values():
            b.setChecked(False)
        for b in getattr(self, "admin_buttons", {}).values():
            b.setChecked(False)
        self.status.showMessage("Inicio: resumen global (solo lectura, sin cambios)")
        self._refresh_active_git_bar()

    def _show_profile_admin(self, key: str) -> None:
        page = self._profile_admin_pages.get(key)
        if page is None:
            return
        self.stacked.setCurrentWidget(page)
        for name, button in self.admin_buttons.items():
            button.setChecked(name == key)
        for button in self.repo_buttons.values():
            button.setChecked(False)
        self.status.showMessage(
            "Archivos excluidos del perfil" if key == "excluidos"
            else "Archivos sin pertenencia resuelta"
        )
        self._refresh_active_git_bar()

    def _refresh_profile_admin_pages(self) -> None:
        if self.profile is None or self.profile_analysis is None:
            return
        from gipler.gui.profile_window import ProfileListPage

        old_current = self.stacked.currentWidget() if hasattr(self, "stacked") else None
        current_admin = next(
            (
                key for key, page in self._profile_admin_pages.items()
                if page is old_current
            ),
            None,
        )
        for page in self._profile_admin_pages.values():
            self.stacked.removeWidget(page)
            page.deleteLater()
        self._profile_admin_pages.clear()

        pages = (
            (
                "excluidos",
                self.profile_analysis.inventory.excluded,
                "Ningún archivo excluido",
                "excluded",
            ),
            (
                "indeterminados",
                self.profile_analysis.membership_review_entries,
                "Ningún archivo indeterminado",
                "indeterminate",
            ),
        )
        for key, entries, empty_text, mode in pages:
            page = ProfileListPage(
                entries,
                empty_text,
                mode=mode,
                eligible_keys=set(),
                parent=self,
                unassigned=(
                    self.profile_analysis.unassigned_new
                    if key == "indeterminados"
                    else ()
                ),
                targets=self._assignment_targets(),
            )
            page.selected.connect(self._inspect_profile_entry)
            page.activated.connect(self._activate_profile_entry)
            page.explorer_requested.connect(self._open_profile_item_explorer)
            page.exclude_requested.connect(self._exclude_profile_item)
            page.restore_requested.connect(self._restore_profile_exclusion)
            page.rule_requested.connect(self._create_rule_for_profile_entry)
            page.assign_requested.connect(self._assign_new_file)
            page.copy_selection_changed.connect(self._on_tree_copy_selection_changed)
            page.sync_selection(self.selection_ctrl.keys)
            self._profile_admin_pages[key] = page
            self.stacked.addWidget(page)
        if current_admin is not None:
            self.stacked.setCurrentWidget(self._profile_admin_pages[current_admin])

    def _inspect_profile_entry(self, entry) -> None:
        if entry is None:
            self.inicio_panel.file_info.setText("Sin archivo seleccionado")
            return
        physical = getattr(entry, "physical", entry)
        details = [
            f"Ruta: {physical.path}",
            f"Tipo: {physical.kind}",
            "Dev: "
            + (
                "existe"
                if os.path.lexists(
                    os.path.join(self.profile.work_dir, *physical.path.split("/"))
                )
                else "no existe"
            ),
        ]
        if hasattr(entry, "membership"):
            details.append(f"Pertenencia: {entry.membership.state.value}")
            details.append(
                "Referencias: "
                + (", ".join(entry.membership.source_ids) or "ninguna")
            )
        if getattr(physical, "exclusion_rule", ""):
            kind = "heredada" if physical.exclusion_inherited else "directa"
            details.append(
                f"Exclusión {kind}: {physical.exclusion_rule}"
            )
        self.inicio_panel.file_info.setText("\n".join(details))

    def _activate_profile_entry(self, entry) -> None:
        if self.profile_analysis is None or not hasattr(entry, "membership"):
            return
        candidates = [
            source_id
            for source_id in entry.membership.source_ids
            if source_id in self.profile_analysis.comparison_roots
            and any(
                row.path == entry.path
                for row in self.profile_analysis.rows_by_source.get(source_id, ())
            )
        ]
        source_id = (
            candidates[0]
            if len(candidates) == 1
            else entry.membership.destination_source_id
            if not candidates
            else None
        )
        if source_id is None:
            self.status.showMessage(
                "Seleccione una referencia para comparar este elemento compartido o ambiguo."
            )
            return
        row = next(
            (
                candidate
                for candidate in self.profile_analysis.rows_by_source.get(source_id, ())
                if candidate.path == entry.path
            ),
            None,
        )
        root = self._repo_root_for(source_id)
        if row is None or not root:
            self.status.showMessage("No hay una comparación física disponible.")
            return
        from gipler.gui.comparison_window import ComparisonWindow

        window = ComparisonWindow(row, self.profile.work_dir, root, self)
        window.show()
        if not hasattr(self, "_comparison_windows"):
            self._comparison_windows = []
        self._comparison_windows.append(window)

    def _open_profile_item_explorer(self, entry) -> None:
        physical = getattr(entry, "physical", entry)
        path = os.path.join(self.profile.work_dir, *physical.path.split("/"))
        target = (
            os.path.abspath(path)
            if physical.kind == "directory"
            else os.path.dirname(os.path.abspath(path))
        )
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not os.path.isdir(target):
            self.status.showMessage(f"No existe el directorio: {target}")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(target)):
            self.status.showMessage(f"No se pudo abrir: {target}")

    def _exclude_profile_item(self, entry) -> None:
        physical = getattr(entry, "physical", entry)
        self.exclude_path(physical.path, physical.kind == "directory")

    def _restore_profile_exclusion(self, entry) -> None:
        physical = getattr(entry, "physical", entry)
        rule = getattr(physical, "exclusion_rule", "")
        if not rule:
            return
        if physical.exclusion_inherited or physical.is_directory:
            from PySide6.QtWidgets import QMessageBox

            if QMessageBox.question(
                self,
                "Restaurar exclusión",
                f"Esta regla puede restaurar otros elementos: {rule}\n"
                "¿Retirar la regla del perfil?",
            ) != QMessageBox.Yes:
                return
        from gipler.profile import remove_exclusion

        try:
            remove_exclusion(self.profile.id, rule)
        except (OSError, ValueError) as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "No se pudo restaurar", str(exc))
            return
        self.reanalyze()

    def _create_rule_for_profile_entry(self, entry) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from gipler.profile import ProfileError, Source, new_source_id, save_profile

        name, accepted = QInputDialog.getText(
            self, "Reconocer mediante regla", "Nombre de la nueva referencia:"
        )
        if not accepted or not name.strip():
            return
        patterns = [entry.path]
        if getattr(entry, "kind", "") == "directory":
            patterns.append(entry.path.rstrip("/") + "/")
        source = Source(
            id=new_source_id(),
            name=name.strip(),
            kind="rules",
            order=self.profile.next_source_order(),
            config={"patterns": patterns},
        )
        self.profile.add_source(source)
        try:
            save_profile(self.profile)
        except (OSError, ProfileError) as exc:
            QMessageBox.critical(self, "No se pudo guardar la referencia", str(exc))
            return
        self.reanalyze()

    def _assignment_targets(self) -> list[tuple[str, str]]:
        """Directorios de referencia activos del perfil abierto (dinámico)."""
        if self.profile is None:
            return []
        return [
            (source.id, source.name)
            for source in sorted(self.profile.sources, key=lambda item: item.order)
            if source.enabled
            and source.kind == "reference_directory"
            and source.acts_as_recognizer
        ]

    def _assign_new_file(self, entry_or_path, source_id: str) -> None:
        """Registra la pertenencia de un archivo nuevo. Sin copia ni escritura
        en el árbol de trabajo: sólo persiste la decisión en el perfil."""
        from PySide6.QtWidgets import QMessageBox
        from gipler.profile import ProfileError, save_profile

        path = getattr(entry_or_path, "path", entry_or_path)
        if not isinstance(path, str) or not path or self.profile is None:
            return
        target = self.profile.source(source_id)
        target_name = target.name if target is not None else source_id
        try:
            self.profile.assign_path(path, source_id)
            save_profile(self.profile)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo asignar", str(exc))
            return
        self.reanalyze()
        self.status.showMessage(
            f"«{path}» asignado a {target_name} (sin copia; decisión de pertenencia)"
        )

    def _show_compare(self, dest: str | None = None) -> None:
        """Muestra la página de comparación preservando selección y ops_cache."""
        sent = getattr(self, "stacked", None)
        if sent is None:
            return
        page = sent.widget(1)
        sent.setCurrentWidget(page)
        if dest is not None:
            for name, b in self.repo_buttons.items():
                b.setChecked(name == dest)
        self._refresh_active_git_bar()
        self.status.showMessage(f"Vista: {self._destination} · seleccionados: {len(self.selection_ctrl)}")

    def _on_repo(self, button: str) -> None:
        for name, b in self.repo_buttons.items():
            b.setChecked(name == button)
        self.set_destination(button)
        self._show_compare(button)

    # Accesores estables para los tests.
    def repo_names(self) -> list[str]:
        return list(self.repo_buttons.keys())

    def panels(self) -> tuple[ComparisonPanel, ComparisonPanel]:
        return self.dev_panel, self.dest_panel

    def _invalidate_review(self) -> None:
        """Invalida la revisión y su autorización: no queda ningún
        conjunto residual ejecutable sin autorización vigente."""
        self.ops_cache = []
        self._prepared_token = None
        self._authorized_token = None

    def _execute_from_panel(self) -> None:
        if self._prepared_token is None or self._authorized_token is not self._prepared_token:
            self.status.showMessage(
                "No hay una revisión autorizada vigente; prepare y autorice las operaciones."
            )
            return
        if self.ops_cache and any(o.status == "copiable" for o in self.ops_cache):
            self._authorized_token = None
            self.authorize_and_execute(self.ops_cache)

    def expand_changes(self) -> None:
        """Expande directorios con archivos con cambios relevantes e
        incidencias, y sus antecesores, en ambos exploradores.
        Respeta los filtros proxy (no expande lo oculto)."""
        relevant = ("new_in_dev", "modified_in_dev", "missing_in_dev", "not_comparable")
        from PySide6.QtCore import QModelIndex
        if self._view_mode == "git":
            source_model = self.git_tree_model
            panels = ((self.dest_panel, self.repo_proxy),)
        else:
            source_model = self.tree_model
            panels = (
                (self.dev_panel, self.proxy),
                (self.dest_panel, self.repo_proxy),
            )
        for panel, proxy in panels:
            ancestors: dict[str, QModelIndex] = {}

            def visit(parent_index: QModelIndex) -> None:
                for row_index in range(proxy.rowCount(parent_index)):
                    proxy_index = proxy.index(row_index, 0, parent_index)
                    source_index = proxy.mapToSource(proxy_index)
                    node = source_model.node_at(source_index)
                    if node.row is not None and (
                        node.row.axis_a in relevant
                        or node.row.incidences
                        or not node.row.owner
                        or node.row.owner == "sin determinar"
                        or (
                            self.profile_analysis is None
                            and node.row.destination not in ("principal", "addons")
                        )
                    ):
                        ancestor_index = source_index.parent()
                        while ancestor_index.isValid():
                            ancestor = source_model.node_at(ancestor_index)
                            ancestors[ancestor.path] = ancestor_index
                            ancestor_index = ancestor_index.parent()
                    if node.is_dir:
                        visit(proxy_index)

            visit(QModelIndex())
            for source_index in ancestors.values():
                proxy_index = proxy.mapFromSource(source_index)
                if proxy_index.isValid() and proxy.rowCount(proxy_index) > 0:
                    panel.tree.expand(proxy_index)

    def _navigate_to_dir(self, dirname: str) -> None:
        self.search_edit.setText(dirname)

    def _update_summary(self) -> None:
        self._refresh_copy_eligibility()
        roots = (
            {
                source.id: (
                    self.profile_analysis.comparison_roots.get(source.id)
                    or self.profile_analysis.destination_roots.get(source.id, "")
                )
                for source in self.profile.sources
            }
            if self.profile_analysis is not None
            else {
                "principal": self.meta.get("principal", ""),
                "addons": self.meta.get("addons", ""),
            }
        )
        self.inicio_panel.set_location_roots(
            self.meta.get("dev", ""),
            roots,
        )
        if self.profile_analysis is not None:
            self.inicio_panel.set_destinations(
                [
                    (source.id, source.name)
                    for source in sorted(self.profile.sources, key=lambda source: source.order)
                ],
                self._destination,
            )
        self.inicio_panel.update_from(
            self.rows,
            self.ops_cache,
            self.selection_ctrl.keys,
            self._eligible_copy_keys or set(),
        )
        if self.profile_analysis is not None:
            self.inicio_panel.set_assignment_targets(self._assignment_targets())
            self.inicio_panel.set_pending_assignments(
                self.profile_analysis.unassigned_new
            )
        else:
            self.inicio_panel.set_pending_assignments(())
        self.inicio_panel.set_empty_state(not self.rows)
        # Botón Ejecutar independiente (zona de controles, no en la lista):
        n_exec = sum(1 for o in self.ops_cache if getattr(o, "status", None) == "copiable")
        if getattr(self, "btn_execute", None) is not None:
            self.btn_execute.setText(f"Ejecutar copia ({n_exec})")
            self.btn_execute.setEnabled(n_exec > 0 and not self.is_executing)
        # Botón Ejecutar independiente (zona de controles, no en la lista):
        n_exec = sum(1 for o in self.ops_cache if getattr(o, "status", None) == "copiable")
        if getattr(self, "btn_execute", None) is not None:
            self.btn_execute.setText(f"Ejecutar copia ({n_exec})")
            self.btn_execute.setEnabled(n_exec > 0 and not self.is_executing)

    # -- Fase 4: selección lógica, preparación (sin escrituras) -----------
    def toggle_current_selection(self) -> None:
        idx = self.dev_panel.tree.currentIndex()
        if not idx.isValid():
            return
        node = self._source_node(idx)
        if node is None or node.row is None:
            return
        key = selection_key_for(node.row)
        if key is None or key not in (self._eligible_copy_keys or set()):
            return
        before = set(self.selection_ctrl.keys)
        self.selection_ctrl.toggle(key)
        self._after_selection_change(before)

    def _after_selection_change(self, before: set) -> None:
        """Invalida ops_cache solo si la selección cambió de verdad."""
        after = set(self.selection_ctrl.keys)
        if after == before:
            return
        self._invalidate_review()
        changed = sorted(after ^ before)
        self._emit_check_changed(changed)
        self._update_counter()
        self.inicio_panel.sync_operational_state(
            after, self._eligible_copy_keys or set(), self.ops_cache
        )

    def _on_tree_copy_selection_changed(
        self, key: tuple[str, str], checked: bool
    ) -> None:
        if key not in (self._eligible_copy_keys or set()):
            return
        before = set(self.selection_ctrl.keys)
        if checked:
            before.discard(key)
        else:
            before.add(key)
        self._after_selection_change(before)

    def _on_home_copy_selection_changed(self, row, checked: bool) -> None:
        key = selection_key_for(row)
        if key is None or key not in (self._eligible_copy_keys or set()):
            self.inicio_panel.sync_operational_state(
                self.selection_ctrl.keys,
                self._eligible_copy_keys or set(),
                self.ops_cache,
            )
            return
        before = set(self.selection_ctrl.keys)
        if checked:
            self.selection_ctrl.add(key)
        else:
            self.selection_ctrl.discard(key)
        self._after_selection_change(before)

    def _refresh_copy_eligibility(self) -> None:
        if self._eligible_copy_keys is not None:
            return
        from gipler.copy_engine import build_operations

        candidates = self.profile_analysis.copy_rows()
        repos = self.profile_analysis.destination_roots
        keys = {
            key
            for row in candidates
            if (key := selection_key_for(row)) is not None
        }
        operations = build_operations(
            candidates,
            keys,
            self.meta.get("dev", ""),
            repos,
            self.snapshot,
        )
        self._eligible_copy_keys = {
            (operation.destination, operation.path)
            for operation in operations
            if getattr(operation, "status", None) == "copiable"
        }
        removed = self.selection_ctrl.keys - self._eligible_copy_keys
        if removed:
            self.selection_ctrl.keys.intersection_update(self._eligible_copy_keys)
            self._invalidate_review()
        self.tree_model.eligible_keys = self._eligible_copy_keys
        self.tree_model.checked_keys = self.selection_ctrl.keys

    def _emit_check_changed(self, keys: list[tuple[str, str]]) -> None:
        """Emite dataChanged con Qt.CheckStateRole para las filas
        afectadas (sin beginResetModel); ambas vistas se actualizan
        porque comparten el mismo modelo fuente/proxy."""
        if not keys:
            return
        wanted = set(keys)
        from PySide6.QtCore import QModelIndex
        stack = [QModelIndex()]
        found = []
        while stack:
            pidx = stack.pop()
            for r in range(self.tree_model.rowCount(pidx)):
                idx = self.tree_model.index(r, 0, pidx)
                node = self.tree_model.node_at(idx)
                if (
                    node
                    and node.row is not None
                    and selection_key_for(node.row) in wanted
                ):
                    found.append(idx)
                stack.append(idx)
        for idx in found:
            self.tree_model.dataChanged.emit(idx, idx, [Qt.CheckStateRole])

    def select_safe_visible(self) -> None:
        from gipler.gui.selection import is_safe
        before = set(self.selection_ctrl.keys)
        proxy = self.proxy
        for pi in range(proxy.rowCount()):
            pidx = proxy.index(pi, 0)
            node = self._source_node(pidx)
            key = (
                selection_key_for(node.row)
                if node is not None and node.row is not None
                else None
            )
            if (
                node is not None
                and node.row is not None
                and key is not None
                and key in (self._eligible_copy_keys or set())
                and is_safe(node.row)
            ):
                self.selection_ctrl.add(key)
        self._after_selection_change(before)

    def clear_selection(self) -> None:
        before = set(self.selection_ctrl.keys)
        self.selection_ctrl.clear()
        if before:
            self._invalidate_review()
            self._emit_check_changed(sorted(before))
            self._update_counter()
            self.inicio_panel.sync_operational_state(
                self.selection_ctrl.keys,
                self._eligible_copy_keys or set(),
                self.ops_cache,
            )

    def prepare_operations(self, show_dialog: bool = False) -> list:
        """Una única llamada a build_operations; guarda ops_cache y
        muestra la vista previa. Sin escrituras."""
        from gipler.copy_engine import build_operations
        from gipler.gui.operations_dialog import OperationsDialog
        operation_rows = self.profile_analysis.copy_rows()
        repos = self.profile_analysis.destination_roots
        excluded_keys = {
            key
            for row in operation_rows
            if "excluded" in row.incidences
            if (key := selection_key_for(row)) is not None
        }
        token = object()
        self._prepared_token = token
        self._authorized_token = None
        self.ops_cache = build_operations(
            operation_rows,
            set(self.selection_ctrl.keys) - excluded_keys,
            self.meta.get("dev", ""),
            repos,
            self.snapshot,
        )
        self.inicio_panel.sync_operational_state(
            self.selection_ctrl.keys,
            self._eligible_copy_keys or set(),
            self.ops_cache,
        )
        counts = {"copiable": 0, "bloqueada": 0, "identica": 0}
        for o in self.ops_cache:
            if o.status in counts:
                counts[o.status] += 1
        dlg = OperationsDialog(self)
        dlg.set_operations(self.ops_cache)
        self.status.showMessage(
            f"Preparación: {counts['copiable']} copiables, {counts['bloqueada']} bloqueadas, "
            f"{counts['identica']} idénticas (sin ejecutar, sin escrituras)"
        )
        if not show_dialog:
            return self.ops_cache
        dlg.exec()
        if dlg.accepted_authorization and self.ops_cache:
            ops = list(self.ops_cache)
            self._authorized_token = token
            self.authorize_and_execute(ops)
            self._authorized_token = None
            return ops
        # Cancelada o cerrada: invalida la revisión y no deja datos residuales.
        self._invalidate_review()
        self.inicio_panel.sync_operational_state(
            self.selection_ctrl.keys,
            self._eligible_copy_keys or set(),
            self.ops_cache,
        )
        return self.ops_cache

    def authorize_and_execute(self, ops: list) -> None:
        """Autorización explícita: ejecuta en QThread y presenta el
        resultado real del motor, tras lo cual reanaliza."""
        from PySide6.QtCore import QThread
        from gipler.gui.workers.copy_worker import CopyWorker

        if self.is_executing:
            self.status.showMessage("Ya hay una ejecución en curso")
            return
        if not ops:
            return
        self.is_executing = True
        self._set_actions_enabled(False)
        self.status.showMessage(f"Ejecutando {sum(1 for o in ops if o.status == 'copiable')} operación(es)…")
        self._copy_thread = QThread(self)
        self._copy_worker = CopyWorker(list(ops), authorized=True)
        self._copy_worker.moveToThread(self._copy_thread)
        self._copy_thread.started.connect(self._copy_worker.run)
        self._copy_worker.finished.connect(self._on_copy_finished)
        self._copy_worker.failed.connect(self._on_copy_failed)
        self._copy_worker.finished.connect(self._copy_thread.quit)
        self._copy_worker.failed.connect(self._copy_thread.quit)
        self._copy_thread.finished.connect(self._copy_worker.deleteLater)
        self._copy_thread.finished.connect(self._copy_thread.deleteLater)
        self._copy_thread.start()

    def _set_actions_enabled(self, enabled: bool) -> None:
        for b in (getattr(self, "btn_safe", None), getattr(self, "btn_prepare", None),
                  getattr(self, "btn_execute", None), getattr(self, "btn_refresh", None)):
            if b is not None:
                b.setEnabled(enabled)

    def _on_copy_finished(self, results: list) -> None:
        self.is_executing = False
        self._set_actions_enabled(True)
        copiadas = sum(1 for r in results if r.get("status") == "copiada")
        self.status.showMessage(f"Ejecución terminada: {copiadas}/{len(results)} copiadas")
        try:
            self.reanalyze()
        except Exception:
            self.status.showMessage(f"Execución completada ({copiadas}/{len(results)} copiadas); reanálisis falló, reintente con Reanalizar")
        self.results = results

    def _on_copy_failed(self, message: str) -> None:
        self.is_executing = False
        self._set_actions_enabled(True)
        self.status.showMessage(f"Error de ejecución: {message}")

    def closeEvent(self, event) -> None:
        if self.is_executing:
            self.status.showMessage("Cierre bloqueado: copia en curso")
            event.ignore()
            return
        if self._copy_thread is not None and self._copy_thread.isRunning():
            self._copy_thread.quit()
            if not self._copy_thread.wait(5000):
                self.status.showMessage("Cierre bloqueado: el worker no terminó a tiempo")
                event.ignore()
                return
        for bar in getattr(self, "git_bars", {}).values():
            bar.deactivate()
            bar.controller.shutdown()
        self._invalidate_review()
        super().closeEvent(event)

    def reanalyze(self) -> str:
        """Re-ejecuta el análisis (sin reiniciar) e invalida la selección
        y cualquier preparación previa."""
        from gipler.profile import load_profile
        from gipler.profile_analysis import analyze_profile

        self.profile = load_profile(self.profile.id)
        self.profile_analysis = analyze_profile(self.profile)
        self.rows = [
            row
            for source_rows in self.profile_analysis.rows_by_source.values()
            for row in source_rows
        ]
        self.meta = {
            "dev": self.profile.work_dir,
            **{
                source.id: (
                    self.profile_analysis.comparison_roots.get(source.id)
                    or self.profile_analysis.destination_roots.get(source.id, "")
                )
                for source in self.profile.sources
            },
        }
        self.snapshot = self.profile_analysis.snapshot
        self.proxy.dev_root = self.meta["dev"]
        self.repo_proxy.dev_root = self.meta["dev"]
        self._refresh_profile_admin_pages()
        self._rebuild_profile_destinations()
        self._invalidate_review()
        self._eligible_copy_keys = None
        self.tree_model.set_rows(self.rows, self._destination)
        self.proxy.apply()
        self.repo_proxy.apply()
        self._update_counter()
        self._update_summary()
        self.expand_changes()
        self._refresh_active_git_bar()
        self._update_git_option()
        if self._view_mode == "git":
            if not self._enter_git_view():
                self._view_mode = "todos"
                self._set_axis_b_options("todos")
                self.axis_a_box.blockSignals(True)
                self.axis_a_box.setCurrentIndex(
                    self.axis_a_box.findData("todos")
                )
                self.axis_a_box.blockSignals(False)
        self.apply_filters()
        if self._active_git_bar is not None:
            self._active_git_bar.refresh_status()
        kept = len(self.selection_ctrl.keys)
        return (
            "Análisis actualizado; "
            f"{kept} selección(es) conservada(s) si sigue(n) siendo elegible(s); "
            "se requiere nueva revisión para copiar"
        )

    def _rebuild_profile_destinations(self) -> None:
        if self.profile is None:
            return
        current = self._destination
        for button in self.repo_buttons.values():
            self.nav_group.removeButton(button)
            for action in self.nav_toolbar.actions():
                if action.defaultWidget() is button:
                    self.nav_toolbar.removeAction(action)
                    break
            button.deleteLater()
        self.repo_buttons.clear()
        sources = sorted(self.profile.sources, key=lambda source: source.order)
        for source in sources:
            button = EditorialNavButton(
                source.name if source.enabled else f"{source.name} (desactivada)"
            )
            button.setCheckable(True)
            button.setEnabled(source.enabled)
            button.clicked.connect(
                lambda _checked=False, source_id=source.id: self._on_repo(button=source_id)
            )
            self.repo_buttons[source.id] = button
            self.nav_group.addButton(button)
            self.nav_toolbar.insertWidget(self._admin_nav_actions[0], button)
        current_source = self.profile.source(current)
        if current not in self.repo_buttons or current_source is None or not current_source.enabled:
            self._destination = next(
                (source.id for source in sources if source.enabled),
                "sin determinar",
            )
        for source_id, button in self.repo_buttons.items():
            button.setChecked(source_id == self._destination)
        self._sync_git_bars()
        self.set_destination(self._destination)
        if self._destination == "sin determinar":
            self._show_inicio()

    def _switch_profile(self) -> None:
        from PySide6.QtWidgets import QDialog
        from gipler.profile import ProfileError, set_last_profile_id

        dialog = ProfileSwitchDialog(self)
        if dialog.exec() != QDialog.Accepted or not dialog.profile_id:
            return
        try:
            set_last_profile_id(dialog.profile_id)
        except ProfileError:
            pass
        self._open_profile_window(dialog.profile_id)

    def _admin_profile(self) -> None:
        if self.profile is None:
            return
        ProfileAdminDialog(self).exec()

    def _manage_profiles(self) -> None:
        from PySide6.QtWidgets import QDialog
        from gipler.gui.profile_window import ProfileLauncherDialog
        from gipler.profile import profile_exists

        dialog = ProfileLauncherDialog(self)
        accepted = dialog.exec() == QDialog.Accepted
        current_id = self.profile.id if self.profile is not None else None
        current_missing = current_id is not None and not profile_exists(current_id)
        if not accepted:
            if current_missing:
                self._open_profile_window(None)
            return
        if not dialog.profile_id:
            return
        if dialog.profile_id == current_id and not current_missing:
            return
        self._open_profile_window(dialog.profile_id)

    def _open_profile_window(self, profile_id: str | None) -> None:
        from PySide6.QtWidgets import QMessageBox
        from gipler.profile import load_profile

        try:
            profile = load_profile(profile_id) if profile_id else None
            window = GiplerWindow(profile=profile)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "No se pudo abrir el perfil", str(exc))
            return
        window.show()
        QApplication.instance()._gipler_window = window
        self.close()

    def _rename_active_profile(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from gipler.profile import ProfileError, rename_profile

        name, accepted = QInputDialog.getText(
            self, "Renombrar perfil", "Nombre:", text=self.profile.name
        )
        if not accepted:
            return
        try:
            self.profile = rename_profile(self.profile.id, name)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo renombrar", str(exc))
            return
        self.setWindowTitle(f"Gipler — {self.profile.name}")
        self._update_profile_menu_label()

    def _update_profile_menu_label(self) -> None:
        for action in self.menuBar().actions():
            if action.text() == "Perfiles" and action.menu():
                actions = action.menu().actions()
                if actions:
                    actions[0].setText(f"Activo: {self.profile.name}")
                break

    def _change_profile_work_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from gipler.profile import ProfileError, save_profile

        directory = QFileDialog.getExistingDirectory(
            self, "Directorio de trabajo", self.profile.work_dir
        )
        if not directory:
            return
        self.profile.work_dir = os.path.abspath(directory)
        try:
            save_profile(self.profile)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return
        self.reanalyze()

    def _configure_source(self, parent, source=None) -> str | None:
        """Abre el diálogo de configuración de una referencia y aplica los
        cambios al perfil. Devuelve el id de la referencia o None."""
        from gipler.gui.profile_window import SourceDialog, confirm_source_baseline
        from gipler.profile import new_source_id

        source_dialog = SourceDialog(source, parent, self.profile.sources)
        if not source_dialog.exec():
            return None
        updated = source_dialog.configured_source()
        if updated is None:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                parent,
                "Configuración incompleta",
                "Indique un nombre y un directorio para comparar.",
            )
            return None
        if source is None:
            updated.id = new_source_id()
            updated.order = self.profile.next_source_order()
            if not confirm_source_baseline(self.profile, updated, parent):
                return None
            self.profile.add_source(updated)
        else:
            root_changed = (
                source.kind != updated.kind
                or os.path.normcase(
                    os.path.abspath(os.path.expanduser(source.root))
                )
                != os.path.normcase(
                    os.path.abspath(os.path.expanduser(updated.root))
                )
                or os.path.normcase(
                    os.path.abspath(
                        os.path.expanduser(source.sync_destination or source.root)
                    )
                )
                != os.path.normcase(
                    os.path.abspath(
                        os.path.expanduser(updated.sync_destination or updated.root)
                    )
                )
            )
            establish_new_baseline = (
                updated.kind == "reference_directory" and root_changed
            )
            if establish_new_baseline and not confirm_source_baseline(
                self.profile, updated, parent
            ):
                return None
            source.name = updated.name
            source.kind = updated.kind
            source.root = updated.root
            source.enabled = updated.enabled
            source.acts_as_recognizer = updated.acts_as_recognizer
            source.acts_as_destination = updated.acts_as_destination
            source.sync_destination = updated.sync_destination
            source.sync_enabled = updated.sync_enabled
            source.destination_source_id = updated.destination_source_id
            source.config = updated.config
            if establish_new_baseline:
                source.baseline = updated.baseline
        return updated.id

    def _manage_sources(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QHBoxLayout, QListWidget,
            QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
        )
        from gipler.profile import ProfileError, save_profile, load_profile

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Referencias — {self.profile.name}")
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        layout.addWidget(listing)

        def refill(selected_id=None):
            listing.clear()
            for source in sorted(self.profile.sources, key=lambda item: item.order):
                label = source.name if source.enabled else f"{source.name} (desactivada)"
                if source.kind == "reference_directory":
                    label += (
                        f" — línea de base: {source.baseline.established_at}"
                        if source.baseline is not None
                        else " — sin línea de base"
                    )
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, source.id)
                listing.addItem(item)
                if source.id == selected_id:
                    listing.setCurrentItem(item)

        def configure(source=None):
            source_id = self._configure_source(dialog, source)
            if source_id is not None:
                refill(source_id)

        buttons = QHBoxLayout()
        add = QPushButton("Agregar…")
        edit = QPushButton("Editar…")
        toggle = QPushButton("Desactivar")
        set_baseline = QPushButton("Establecer línea de base…")
        remove_baseline = QPushButton("Retirar línea de base…")
        remove = QPushButton("Eliminar")
        up = QPushButton("Subir")
        down = QPushButton("Bajar")
        for button in (
            add, edit, toggle, set_baseline, remove_baseline, remove, up, down
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        add.clicked.connect(lambda: configure())
        edit.clicked.connect(
            lambda: configure(self.profile.source(listing.currentItem().data(Qt.UserRole)))
            if listing.currentItem() else None
        )

        def toggle_selected():
            item = listing.currentItem()
            source = self.profile.source(item.data(Qt.UserRole)) if item else None
            if source is None:
                return
            source.enabled = not source.enabled
            refill(source.id)

        def update_toggle_label():
            item = listing.currentItem()
            source = self.profile.source(item.data(Qt.UserRole)) if item else None
            toggle.setEnabled(source is not None)
            set_baseline.setEnabled(
                source is not None and source.kind == "reference_directory"
            )
            remove_baseline.setEnabled(
                source is not None and source.baseline is not None
            )
            set_baseline.setText(
                "Restablecer línea de base…"
                if source is not None and source.baseline is not None
                else "Establecer línea de base…"
            )
            toggle.setText(
                "Desactivar" if source is None or source.enabled else "Activar"
            )

        def set_selected_baseline():
            item = listing.currentItem()
            source = self.profile.source(item.data(Qt.UserRole)) if item else None
            if source is None or source.kind != "reference_directory":
                return
            from gipler.gui.profile_window import confirm_source_baseline

            if source.baseline is not None:
                answer = QMessageBox.question(
                    dialog,
                    "Restablecer línea de base",
                    "Se reemplazará la línea de base anterior por el estado actual. "
                    "La clasificación de archivos y las operaciones propuestas "
                    "pueden cambiar; no se modificará ningún archivo físico. "
                    "¿Continuar?",
                )
                if answer != QMessageBox.Yes:
                    return
            if not confirm_source_baseline(self.profile, source, dialog):
                return
            refill(source.id)

        def remove_selected_baseline():
            item = listing.currentItem()
            source = self.profile.source(item.data(Qt.UserRole)) if item else None
            if source is None or source.baseline is None:
                return
            answer = QMessageBox.question(
                dialog,
                "Retirar línea de base",
                "Al retirar la línea de base, Gipler dejará de distinguir el "
                "contenido preexistente del contenido posterior en esta referencia. "
                "Los estados y las operaciones propuestas pueden cambiar; no se "
                "modificará ningún archivo físico. ¿Continuar?",
            )
            if answer != QMessageBox.Yes:
                return
            source.baseline = None
            refill(source.id)

        def remove_selected():
            item = listing.currentItem()
            source = self.profile.source(item.data(Qt.UserRole)) if item else None
            if source is None:
                return
            if QMessageBox.question(
                dialog, "Eliminar referencia",
                f"¿Retirar «{source.name}» del perfil? No se modificarán sus archivos.",
            ) == QMessageBox.Yes:
                self.profile.remove_source(source.id)
                refill()

        def move(delta):
            item = listing.currentItem()
            if item is None:
                return
            source_id = item.data(Qt.UserRole)
            source = self.profile.source(source_id)
            self.profile.reorder_source(
                source_id, max(0, min(source.order + delta, len(self.profile.sources) - 1))
            )
            refill(source_id)

        remove.clicked.connect(remove_selected)
        toggle.clicked.connect(toggle_selected)
        set_baseline.clicked.connect(set_selected_baseline)
        remove_baseline.clicked.connect(remove_selected_baseline)
        listing.currentItemChanged.connect(
            lambda _current, _previous: update_toggle_label()
        )
        up.clicked.connect(lambda: move(-1))
        down.clicked.connect(lambda: move(1))
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        layout.addWidget(box)
        refill()
        update_toggle_label()
        if not dialog.exec():
            self.profile = load_profile(self.profile.id)
            return
        try:
            save_profile(self.profile)
        except (ProfileError, OSError) as exc:
            self.profile = load_profile(self.profile.id)
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return
        self.reanalyze()


def _app_icon() -> str:
    """Ruta del icono oficial empaquetado (nunca falla si falta el recurso)."""
    from gipler.resources import master_icon

    try:
        path = master_icon()
    except Exception:
        return ""
    return path if os.path.isfile(path) else ""


def create_application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Gipler")
    app.setDesktopFileName("gipler")
    icon = _app_icon()
    if icon:
        app.setWindowIcon(QIcon(icon))
    return app


def _startup_profile():
    from gipler.profile import ProfileError, last_profile_id, list_profiles

    profiles = list_profiles()
    if not profiles:
        return None
    try:
        last_id = last_profile_id()
    except ProfileError:
        last_id = None
    return next((profile for profile in profiles if profile.id == last_id), profiles[0])


def main() -> int:
    app = create_application()
    profile = _startup_profile()
    if profile is None:
        from PySide6.QtWidgets import QDialog
        from gipler.gui.profile_window import ProfileLauncherDialog

        dialog = ProfileLauncherDialog()
        if dialog.exec() != QDialog.Accepted or not dialog.profile_id:
            return 0
        from gipler.profile import load_profile

        profile = load_profile(dialog.profile_id)
    window = GiplerWindow(profile=profile)
    window.show()
    app._gipler_window = window
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
