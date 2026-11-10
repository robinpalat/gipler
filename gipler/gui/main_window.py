"""Ventana principal (Fases 1-5 spec GUI QT 1.0 + rediseño de usabilidad).

Distribución:
- Barra superior: selector de repositorio (segmentado) + acciones.
- Filtros en una sola fila; avanzados en desplegable.
- Zona principal dominante: Dev | Repositorio | Inspector (QSplitter).
- Barra inferior informativa.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt
from gipler.gui.comparison_view import ComparisonPanel
from gipler.gui.summary_panel import SummaryPanel
from gipler.gui.models.comparison_tree import ComparisonTreeModel
from gipler.gui.models.filter_model import FilterModel, visible_file_count

DESTINATIONS = ("principal", "addons", "sin determinar")
AXIS_A = ("todos", "new_in_dev", "modified_in_dev", "identical", "missing_in_dev")
AXIS_B = ("todos", "tracked_modified", "tracked_clean", "untracked", "ignored")
REPO_LABELS = {"principal": "Principal", "addons": "Addons", "sin determinar": "Sin determinar"}


class GiplerWindow(QMainWindow):
    def __init__(self, rows: list | None = None, meta: dict | None = None, warnings: list[str] | None = None,
                 snapshot: dict | None = None, parent=None):
        super().__init__(parent)
        self.rows = rows or []
        self.meta = meta or {}
        self.warnings = warnings or []
        self.snapshot = snapshot if snapshot is not None else {"dev": {}, "repos": {}}
        from gipler.gui.selection import SelectionController
        self.selection_ctrl = SelectionController()
        self._eligible_copy_keys: set[tuple[str, str]] | None = None
        self.ops_cache: list = []
        self._destination = "principal"
        self.is_executing = False
        self._copy_thread = None
        self._copy_worker = None
        self._build_ui()
        self._build_models()
        self._apply_initial_theme()
        self._connect_sync()
        self.refresh_owners()
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
    def apply_filters(self) -> None:
        a = self.axis_a_box.currentText()
        b = self.axis_b_box.currentText()
        inc = self.incidences_box.isChecked()
        txt = self.search_edit.text()
        owner = self.owner_box.currentText()
        # Mismo criterio en ambos paneles (modelos con cabeceras propias).
        for p in (self.proxy, self.repo_proxy):
            p.set_criteria(
                axis_a=None if a == "todos" else a,
                axis_b=None if b == "todos" else b,
                incidences=inc,
                search=txt,
                owner="" if owner == "todos" else owner,
            )
        self.expand_changes()
        self._update_counter()

    def _update_counter(self) -> None:
        n = visible_file_count(self.proxy)
        selected = len(self.selection_ctrl)
        self.status.showMessage(f"Vista: {self._destination} · visibles: {n} archivos · seleccionados: {selected}")

    def set_destination(self, dest: str) -> None:
        if dest not in DESTINATIONS:
            return
        self._destination = dest
        self.repo_proxy.repo_root = self._repo_root_for(dest)
        self.tree_model.set_rows(self.rows, dest)
        self.proxy.apply()
        self.repo_proxy.apply()
        self._update_counter()
        self._update_summary()
        self.expand_changes()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("Gipler")
        self.resize(1440, 900)
        self.statusBar().showMessage("Análisis no ejecutado (Fase 1)")

        # Barra superior: pestañas (Inicio + destinos) y, a la derecha,
        # el menú de herramientas (no son espacios de trabajo).
        bar = QToolBar("Principal", self)
        self.addToolBar(bar)
        self.tools_menu = self.menuBar().addMenu("Herramientas")
        act_update = QAction("Actualizar", self)
        act_update.triggered.connect(self.reanalyze)
        self.tools_menu.addAction(act_update)
        act_settings = QAction("Configuración", self)
        act_settings.triggered.connect(self.status.showMessage if False else self._open_settings)
        self.tools_menu.addAction(act_settings)
        theme_menu = self.tools_menu.addMenu("Apariencia")
        for name in ("oscuro", "claro"):
            act = QAction("Oscuro grafito" if name == "oscuro" else "Claro", self)
            act.triggered.connect(lambda _c=False, t=name: self.apply_theme(t))
            theme_menu.addAction(act)
        self.repo_buttons: dict[str, QPushButton] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        # Inicio es la primera pestaña de control; el resto son destinos.
        start = QPushButton("Inicio")
        start.setCheckable(True)
        start.clicked.connect(self._show_inicio)
        self.nav_buttons["inicio"] = start
        group.addButton(start)
        bar.addWidget(start)
        for name in DESTINATIONS:
            b = QPushButton(REPO_LABELS[name])
            b.setCheckable(True)
            b.setChecked(name == "principal")
            b.clicked.connect(lambda _checked=False, dest=name: self._on_repo(button=dest))
            self.repo_buttons[name] = b
            group.addButton(b)
            bar.addWidget(b)

        # Filtros: fila única + panel avanzado desplegable.
        filter_row = QWidget()
        fr = QHBoxLayout(filter_row)
        self.axis_a_box = QComboBox()
        self.axis_a_box.addItems(AXIS_A)
        self.axis_b_box = QComboBox()
        self.axis_b_box.addItems(AXIS_B)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por nombre o ruta…")
        self.search_edit.setMinimumWidth(220)
        self.incidences_box = QCheckBox("Incidencias")
        self.owner_box = QComboBox()
        self.owner_box.addItems(["todos"])
        self.advanced_button = QToolButton()
        self.advanced_button.setText("Filtros avanzados")
        self.advanced_button.setCheckable(True)
        self.advanced_panel = QWidget()
        adv_layout = QHBoxLayout(self.advanced_panel)
        adv_layout.addWidget(self.incidences_box)
        adv_layout.addWidget(self.owner_box)
        self.advanced_panel.setVisible(False)
        fr.addWidget(self.axis_a_box)
        fr.addWidget(self.axis_b_box)
        fr.addWidget(self.search_edit)
        fr.addWidget(self.advanced_button)
        self.filter_bar = filter_row
        self.advanced_button.toggled.connect(self.advanced_panel.setVisible)
        self.axis_a_box.currentTextChanged.connect(lambda _x: self.apply_filters())
        self.axis_b_box.currentTextChanged.connect(lambda _x: self.apply_filters())
        self.incidences_box.toggled.connect(lambda _x: self.apply_filters())
        self.search_edit.textChanged.connect(lambda _x: self.apply_filters())
        self.owner_box.currentTextChanged.connect(lambda _x: self.apply_filters())

        # Zona principal: QStackedWidget (Inicio | comparación).
        self.stacked = QStackedWidget()
        central = QWidget()
        central_layout = QVBoxLayout(central)
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
        self.btn_execute = self.inicio_panel.btn_execute
        self.btn_execute.clicked.connect(self._execute_from_panel)
        self.btn_safe = self.inicio_panel.btn_safe
        self.btn_safe.clicked.connect(self.select_safe_visible)
        self.btn_prepare = self.inicio_panel.btn_prepare
        self.btn_prepare.clicked.connect(lambda: self.prepare_operations(show_dialog=True))
        splitter = QSplitter(Qt.Horizontal)
        self.dev_panel = ComparisonPanel("Dev")
        self.dest_panel = ComparisonPanel("Repositorio")
        splitter.addWidget(self.dev_panel)
        splitter.addWidget(self.dest_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter
        central_layout.addWidget(filter_row)
        filter_row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.advanced_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        central_layout.addWidget(self.advanced_panel)
        central_layout.addWidget(splitter)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        central_layout.setStretch(2, 1)
        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.bottom_splitter.addWidget(central)
        central.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        compare_page = QWidget()
        compare_layout = QVBoxLayout(compare_page)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.addWidget(central)
        self.stacked.addWidget(self.inicio_panel)
        self.stacked.addWidget(compare_page)
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
        self.tree_model.dataChanged.emit(self.tree_model.index(0, 0), self.tree_model.index(0, 0))
        self.status.showMessage(f"Tema: {'Oscuro grafito' if theme == 'oscuro' else 'Claro'} (guardado)")

    def _apply_initial_theme(self) -> None:
        from gipler.gui.theme import apply_theme, load_preference
        theme = load_preference()
        apply_theme(theme)
        self.tree_model.semantic_theme = theme

    def exclude_path(self, rel: str, is_dir: bool) -> None:
        """Guarda la exclusión (config local) e invalida la vista con
        el reanálisis existente (no modifica archivos ni Git)."""
        self.ops_cache = []
        self.selection_ctrl.clear()
        from gipler.ignore import add_pattern

        add_pattern(rel.rstrip("/") + "/" if is_dir else rel)
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
        self.status.showMessage("Inicio: resumen global (solo lectura, sin cambios)")

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
        self.status.showMessage(f"Vista: {self._destination} · seleccionados: {len(self.selection_ctrl)}")

    def _open_settings(self) -> None:
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
        )
        from gipler.config import configured_paths, save_paths

        dlg = QDialog(self)
        dlg.setWindowTitle("Configuración de Gipler")
        dlg.setModal(True)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Rutas externas administradas por Gipler:"))
        form = QFormLayout()
        fields = {}
        for key, label, initial in zip(
            ("dev", "principal", "addons"),
            ("Origen Dev", "Repositorio Principal", "Repositorio Add-ons"),
            configured_paths(),
        ):
            field = QLineEdit(initial)
            fields[key] = field
            browse = QPushButton("Examinar…")
            browse.clicked.connect(
                lambda _checked=False, target=field: target.setText(
                    QFileDialog.getExistingDirectory(dlg, "Seleccionar directorio", target.text())
                    or target.text()
                )
            )
            row = QHBoxLayout()
            row.addWidget(field)
            row.addWidget(browse)
            form.addRow(label, row)
        v.addLayout(form)
        v.addWidget(QLabel("Las rutas y preferencias se guardan en la configuración de usuario."))
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=dlg
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        if dlg.exec():
            paths = [fields[key].text().strip() for key in ("dev", "principal", "addons")]
            if any(not path for path in paths):
                self.status.showMessage("Las tres rutas deben estar configuradas.")
                return
            save_paths(*paths)
            self.meta.update(dict(zip(("dev", "principal", "addons"), paths)))
            self.status.showMessage("Rutas de Gipler guardadas; reanalizando…")
            self.reanalyze()
        self._show_inicio()

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

    def _execute_from_panel(self) -> None:
        if self.ops_cache and any(o.status == "copiable" for o in self.ops_cache):
            self.authorize_and_execute(self.ops_cache)

    def refresh_owners(self) -> None:
        owners = sorted({r.owner for r in self.rows if r.owner and r.owner != "sin determinar"})
        self.owner_box.clear()
        self.owner_box.addItems(["todos"] + owners)

    def expand_changes(self) -> None:
        """Expande directorios con archivos con cambios relevantes e
        incidencias, y sus antecesores, en ambos exploradores.
        Respeta los filtros proxy (no expande lo oculto)."""
        relevant = ("new_in_dev", "modified_in_dev", "missing_in_dev")
        from PySide6.QtCore import QModelIndex
        for panel, proxy in (
            (self.dev_panel, self.proxy),
            (self.dest_panel, self.repo_proxy),
        ):
            ancestors: dict[str, QModelIndex] = {}

            def visit(parent_index: QModelIndex) -> None:
                for row_index in range(proxy.rowCount(parent_index)):
                    proxy_index = proxy.index(row_index, 0, parent_index)
                    source_index = proxy.mapToSource(proxy_index)
                    node = self.tree_model.node_at(source_index)
                    if node.row is not None and (
                        node.row.axis_a in relevant
                        or node.row.incidences
                        or not node.row.owner
                        or node.row.owner == "sin determinar"
                        or node.row.destination not in ("principal", "addons")
                    ):
                        ancestor_index = source_index.parent()
                        while ancestor_index.isValid():
                            ancestor = self.tree_model.node_at(ancestor_index)
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
        self.inicio_panel.set_location_roots(
            self.meta.get("dev", ""),
            {
                "principal": self.meta.get("principal", ""),
                "addons": self.meta.get("addons", ""),
            },
        )
        self.inicio_panel.update_from(
            self.rows,
            self.ops_cache,
            self.selection_ctrl.keys,
            self._eligible_copy_keys or set(),
        )
        # Botón Ejecutar independiente (zona de controles, no en la lista):
        n_exec = sum(1 for o in self.ops_cache if getattr(o, "status", None) == "copiable")
        if getattr(self, "btn_execute", None) is not None:
            self.btn_execute.setText(f"Ejecutar copia ({n_exec})")
            self.btn_execute.setEnabled(n_exec > 0 and not self.is_executing)
        owners = sorted({r.owner for r in self.rows if r.owner and r.owner != "sin determinar"})
        self.owner_box.clear()
        self.owner_box.addItems(["todos"] + owners)
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
        key = (node.row.destination, node.path)
        if key not in (self._eligible_copy_keys or set()):
            return
        before = set(self.selection_ctrl.keys)
        self.selection_ctrl.toggle(key)
        self._after_selection_change(before)

    def _after_selection_change(self, before: set) -> None:
        """Invalida ops_cache solo si la selección cambió de verdad."""
        after = set(self.selection_ctrl.keys)
        if after == before:
            return
        self.ops_cache = []
        changed = sorted(after ^ before)
        self._emit_check_changed([k for k in changed if k[0] == self._destination])
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
        key = (row.destination, row.path)
        if key not in (self._eligible_copy_keys or set()):
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
        from gipler.ignore import is_excluded, load_patterns

        repos = {
            "principal": self.meta.get("principal", ""),
            "addons": self.meta.get("addons", ""),
        }
        patterns = load_patterns()
        candidates = {
            (row.destination, row.path)
            for row in self.rows
            if row.destination in repos
            and "excluded" not in row.incidences
            and not is_excluded(row.path, patterns)
        }
        operations = build_operations(
            self.rows,
            candidates,
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
            self.ops_cache = []
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
                if node and node.row is not None and (node.row.destination, node.path) in wanted:
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
            key = (node.row.destination, node.path) if node is not None and node.row is not None else None
            if (
                node is not None
                and node.row is not None
                and key in (self._eligible_copy_keys or set())
                and is_safe(node.row)
            ):
                self.selection_ctrl.add(key)
        self._after_selection_change(before)

    def clear_selection(self) -> None:
        before = set(self.selection_ctrl.keys)
        self.selection_ctrl.clear()
        if before:
            self.ops_cache = []
            self._emit_check_changed([k for k in sorted(before) if k[0] == self._destination])
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
        from gipler.ignore import is_excluded, load_patterns

        repos = {"principal": self.meta.get("principal", ""), "addons": self.meta.get("addons", "")}
        exclusion_patterns = load_patterns()
        excluded_keys = {
            (row.destination, row.path)
            for row in self.rows
            if "excluded" in row.incidences or is_excluded(row.path, exclusion_patterns)
        }
        self.ops_cache = build_operations(
            self.rows,
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
        result = dlg.exec() if show_dialog else 0
        if not show_dialog:
            return self.ops_cache
        if dlg.accepted_authorization and self.ops_cache:
            self.authorize_and_execute(self.ops_cache)
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
        super().closeEvent(event)

    def reanalyze(self) -> str:
        """Re-ejecuta el análisis (sin reiniciar) e invalida la selección
        y cualquier preparación previa."""
        from gipler.analysis import analyze

        _, rows, info = analyze(
            self.meta.get("dev", ""), self.meta.get("principal", ""), self.meta.get("addons", "")
        )
        self.rows = rows
        self.meta = info["meta"]
        self.warnings = info["warnings"]
        self.snapshot = info.get("snapshot", {"dev": {}, "repos": {}})
        self.selection_ctrl.clear()
        self.ops_cache = []
        self._eligible_copy_keys = None
        self.tree_model.set_rows(self.rows, self._destination)
        self.proxy.apply()
        self.repo_proxy.apply()
        self.refresh_owners()
        self._update_counter()
        self._update_summary()
        self.expand_changes()
        return "Análisis actualizado; selección anterior descartada (snapshot cambió)"


def _defaults() -> tuple[str, str, str]:
    from gipler.config import configured_paths

    return configured_paths()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from gipler.analysis import analyze

    dev, principal, addons = _defaults()
    _, rows, info = analyze(dev, principal, addons)
    app = QApplication.instance() or QApplication([])
    window = GiplerWindow(rows=rows, meta=info["meta"], warnings=info["warnings"],
                                snapshot=info.get("snapshot"))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
