"""Diálogos y páginas compartidas del sistema de perfiles."""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gipler.profile import (
    Profile,
    ProfileError,
    ReferenceRoot,
    Source,
    capture_source_baseline,
    create_profile,
    delete_profile,
    list_profiles,
    new_source_id,
    set_last_profile_id,
)
from gipler.profile_analysis import ProfileEntry, analyze_profile
from gipler.selection import selection_key_for_entry
from gipler.recognition import MembershipState
from gipler.gui import icons
from gipler.gui.identity import apply_window_icon
from gipler.gui.profile_hierarchy import (
    HierarchyNode,
    build_excluded_tree,
    build_indeterminate_sections,
)


class EstablishBaselineDialog(QDialog):
    """Explicit, reviewable confirmation of one source's initial state."""

    def __init__(self, profile: Profile, source: Source, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.source = source
        other_roots: dict[str, ReferenceRoot] = {}
        for existing in profile.sources:
            if existing.id == source.id:
                continue
            for path, role in (
                (existing.root, "reference"),
                (existing.sync_destination, "destination"),
            ):
                if not path or not os.path.isdir(os.path.expanduser(path)):
                    continue
                absolute = os.path.abspath(os.path.expanduser(path))
                key = os.path.normcase(absolute)
                other_roots.setdefault(
                    key, ReferenceRoot(absolute, existing.id, role)
                )
        self.other_references = tuple(other_roots.values())
        self.other_reference_dirs = tuple(
            item.root for item in self.other_references
        )
        self.baseline = capture_source_baseline(
            profile.work_dir,
            source.root,
            source.sync_destination or source.root,
            self.other_references,
        )
        self.setWindowTitle("Establecer línea de base")
        apply_window_icon(self)
        self.setMinimumSize(620, 520)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Este es un paso fundamental. Gipler registrará el estado actual de este "
            "directorio como punto de partida de la sincronización.\n\n"
            "Los archivos que ya existen en este momento no serán considerados "
            "incorporaciones nuevas por el hecho de no encontrarse en otras referencias.\n\n"
            "También se registrarán las rutas presentes en las demás referencias "
            "disponibles para no clasificarlas como nuevas en esta.\n\n"
            "A partir de esta confirmación, los archivos que aparezcan posteriormente "
            "podrán identificarse como nuevos en las comparaciones correspondientes."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        details = QFormLayout()
        details.addRow("Directorio de trabajo", QLabel(profile.work_dir))
        details.addRow("Directorio de sincronización", QLabel(source.root))
        if source.sync_destination and os.path.normcase(
            os.path.abspath(os.path.expanduser(source.sync_destination))
        ) != os.path.normcase(os.path.abspath(os.path.expanduser(source.root))):
            details.addRow("Destino configurado", QLabel(source.sync_destination))
        self.inventory_summary = QLabel()
        self.other_reference_summary = QLabel()
        self.uncertain_summary = QLabel()
        details.addRow("Elementos que se registrarán", self.inventory_summary)
        details.addRow("Otras referencias consideradas", self.other_reference_summary)
        details.addRow("Elementos desconocidos o ambiguos", self.uncertain_summary)
        layout.addLayout(details)

        self.review_list = QListWidget()
        self.review_list.setToolTip(
            "Elementos del análisis que siguen sin pertenencia resuelta; establecer "
            "la línea de base no los asigna automáticamente."
        )
        layout.addWidget(self.review_list, 1)

        self.confirmation = QCheckBox(
            "Confirmo que he revisado los elementos y deseo establecer este punto de partida."
        )
        confirmation_text = QLabel(
            "Confirmo que el estado actual de este directorio es el punto de partida "
            "que deseo establecer para esta referencia y que he revisado los elementos "
            "ambiguos o pendientes de identificación."
        )
        confirmation_text.setWordWrap(True)
        layout.addWidget(confirmation_text)
        layout.addWidget(self.confirmation)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.establish_button = QPushButton("Establecer línea de base")
        self.establish_button.setDefault(True)
        self.establish_button.setEnabled(False)
        cancel = QPushButton("Cancelar")
        buttons.addWidget(self.establish_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.confirmation.toggled.connect(self.establish_button.setEnabled)
        self.establish_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self._refresh_review(self.baseline)

    @staticmethod
    def _count_entries(entries) -> tuple[int, int]:
        directories = sum(entry.kind == "dir" for entry in entries)
        return len(entries) - directories, directories

    @staticmethod
    def _quantity(count: int, singular: str, plural: str) -> str:
        return f"{count} {singular if count == 1 else plural}"

    def _refresh_review(self, baseline) -> None:
        candidate = copy.deepcopy(self.profile)
        candidate_source = copy.deepcopy(self.source)
        existing = candidate.source(self.source.id)
        if existing is None:
            candidate.add_source(candidate_source)
        else:
            candidate_source.order = existing.order
            candidate.sources[candidate.sources.index(existing)] = candidate_source
        candidate_source.baseline = baseline
        analysis = analyze_profile(candidate)
        files, directories = self._count_entries(baseline.reference_entries)
        destination_files, destination_directories = self._count_entries(
            baseline.destination_entries
        )
        work_files, work_directories = self._count_entries(baseline.work_entries)
        self.inventory_summary.setText(
            f"Sincronización: {self._quantity(files, 'archivo', 'archivos')} y "
            f"{self._quantity(directories, 'directorio', 'directorios')}; "
            f"destino: {self._quantity(destination_files, 'archivo', 'archivos')} y "
            f"{self._quantity(destination_directories, 'directorio', 'directorios')}; "
            f"trabajo: {self._quantity(work_files, 'archivo', 'archivos')} y "
            f"{self._quantity(work_directories, 'directorio', 'directorios')}."
        )
        self.other_reference_summary.setText(
            f"{len(baseline.other_reference_paths)} rutas preexistentes"
        )
        entries = analysis.indeterminate
        self.uncertain_summary.setText(
            f"{len(entries)} ({sum(item.membership.state == MembershipState.UNKNOWN for item in entries)} "
            f"desconocidos, "
            f"{sum(item.membership.state == MembershipState.AMBIGUOUS for item in entries)} ambiguos)"
        )
        self.review_list.clear()
        for item in entries:
            state = (
                "Ambiguo"
                if item.membership.state == MembershipState.AMBIGUOUS
                else "Desconocido"
            )
            reasons = f" — {', '.join(item.membership.reasons)}" if item.membership.reasons else ""
            self.review_list.addItem(f"{state}: {item.path}{reasons}")
        if not entries:
            self.review_list.addItem("No se detectaron elementos desconocidos ni ambiguos.")

    def accept(self) -> None:
        try:
            current = capture_source_baseline(
                self.profile.work_dir,
                self.source.root,
                self.source.sync_destination or self.source.root,
                self.other_references,
            )
        except (OSError, ProfileError) as exc:
            QMessageBox.critical(
                self,
                "No se pudo capturar la línea de base",
                str(exc),
            )
            return
        if (
            current.work_entries != self.baseline.work_entries
            or current.reference_entries != self.baseline.reference_entries
            or current.destination_entries != self.baseline.destination_entries
            or current.other_reference_paths != self.baseline.other_reference_paths
            or current.other_references != self.baseline.other_references
            or current.work_root != self.baseline.work_root
            or current.reference_root != self.baseline.reference_root
            or current.destination_root != self.baseline.destination_root
        ):
            self.baseline = current
            self.confirmation.setChecked(False)
            try:
                self._refresh_review(current)
            except (OSError, ProfileError) as exc:
                QMessageBox.critical(
                    self,
                    "No se pudo actualizar la revisión",
                    str(exc),
                )
                return
            QMessageBox.warning(
                self,
                "Cambió el contenido",
                "El directorio de trabajo o el de sincronización cambió durante la "
                "revisión. Se actualizó el resumen; vuelva a revisar y confirmar.",
            )
            return
        self.baseline = current
        super().accept()


def confirm_source_baseline(profile: Profile, source: Source, parent=None) -> bool:
    if source.kind != "reference_directory":
        return True
    try:
        dialog = EstablishBaselineDialog(profile, source, parent)
    except (OSError, ProfileError) as exc:
        QMessageBox.critical(
            parent,
            "No se pudo revisar la línea de base",
            str(exc),
        )
        return False
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    source.baseline = dialog.baseline
    return True


class ProfileListPage(QWidget):
    selected = Signal(object)
    activated = Signal(object)
    restore_requested = Signal(object)
    rule_requested = Signal(object)
    copy_selection_changed = Signal(object, bool)
    exclude_requested = Signal(object)
    explorer_requested = Signal(object)
    # (entrada, id de referencia) — pertenencia explícita, sin copia.
    assign_requested = Signal(object, str)

    def __init__(
        self,
        entries: tuple | list,
        empty_text: str,
        mode: str = "inventory",
        disabled: bool = False,
        eligible_keys: set[tuple[str, str]] | None = None,
        parent=None,
        unassigned: tuple | list = (),
        targets: tuple | list = (),
        included: tuple | list = (),
        all_entries: tuple | list = (),
    ):
        super().__init__(parent)
        self.mode = mode
        self._syncing_checks = False
        self._targets = [(str(source_id), str(name)) for source_id, name in targets]
        self._unassigned = tuple(unassigned or ())
        self._eligible_keys = eligible_keys
        if mode == "excluded":
            hierarchy = build_excluded_tree(entries, included)
        elif mode == "indeterminate":
            hierarchy = build_indeterminate_sections(
                entries, self._unassigned, all_entries
            )
        else:
            hierarchy = self._flat_nodes(entries)
        self._hierarchy = hierarchy
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.setObjectName("panelSurface")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por ruta…")
        self.search.setObjectName("searchField")
        self.list = QTreeWidget()
        self.list.setObjectName("semanticTree")
        self.list.setColumnCount(1)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(True)
        self.list.setIndentation(16)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._open_context_menu)
        self.empty_label = QLabel(empty_text)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("emptyState")
        has_items = bool(hierarchy)
        self.empty_label.setVisible(not has_items)
        self.list.setVisible(has_items)
        layout.addWidget(self.search)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list, 1)
        self.action_row = QWidget()
        actions = QHBoxLayout(self.action_row)
        actions.setContentsMargins(0, 0, 0, 0)
        self.restore_button = QPushButton("Restaurar exclusión")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self._restore)
        self.rule_button = QPushButton("Crear regla para seleccionado")
        self.rule_button.setEnabled(False)
        self.rule_button.clicked.connect(self._create_rule)
        self.restore_button.setVisible(mode == "excluded")
        self.rule_button.setVisible(mode == "indeterminate")
        actions.addWidget(self.restore_button)
        actions.addWidget(self.rule_button)
        self.action_row.setVisible(mode in ("excluded", "indeterminate"))
        layout.addWidget(self.action_row)
        self._populate_tree(hierarchy)
        self.search.textChanged.connect(self._filter)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._activate)
        self.list.itemChanged.connect(self._copy_check_changed)
        if disabled:
            self.search.setEnabled(False)
            self.list.setEnabled(False)
            self.empty_label.setText(empty_text)
            self.empty_label.setVisible(True)
            self.action_row.setVisible(False)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "list"):
            self._refresh_item_visuals()

    def _refresh_item_visuals(self) -> None:
        from gipler.gui.theme import load_preference, semantic

        color = QColor(semantic(load_preference(), "new_in_dev"))

        def visit(item: QTreeWidgetItem) -> None:
            node = item.data(0, Qt.UserRole + 3)
            if node is not None and node.icon:
                item.setIcon(0, icons.icon(node.icon))
            if node is not None and node.is_unassigned:
                item.setForeground(0, color)
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.list.topLevelItemCount()):
            visit(self.list.topLevelItem(index))

    def _flat_nodes(self, entries) -> list[HierarchyNode]:
        nodes: list[HierarchyNode] = []
        for entry in entries:
            kind = getattr(entry, "kind", getattr(getattr(entry, "physical", entry), "kind", "file"))
            nodes.append(
                HierarchyNode(
                    path=getattr(entry, "path", ""),
                    label=self._label(entry),
                    icon="folder" if kind == "directory" else "file",
                    entry=entry,
                    tooltip=self._tooltip(entry),
                    is_dir=kind == "directory",
                )
            )
        return nodes

    @staticmethod
    def _tooltip(entry) -> str:
        tooltip = getattr(entry, "path", "")
        blockers = getattr(entry, "copy_blockers", ())
        if blockers:
            from gipler.copy_policy import describe_blockers

            tooltip += "\nCopia: " + "; ".join(describe_blockers(blockers))
        return tooltip

    @staticmethod
    def _label(entry) -> str:
        physical = getattr(entry, "physical", entry)
        path = getattr(physical, "path", "")
        kind = getattr(physical, "kind", "")
        if isinstance(entry, ProfileEntry):
            state_labels = {
                MembershipState.RECOGNIZED: "Reconocido",
                MembershipState.SHARED: "Compartido (pertenencia múltiple válida)",
                MembershipState.AMBIGUOUS: "Ambiguo o contradictorio",
                MembershipState.UNKNOWN: "Sin reconocimiento",
            }
            return f"{path}  [{state_labels[entry.membership.state]}]"
        if kind == "directory":
            return f"{path}/"
        if kind == "symlink":
            return f"{path}  →"
        rule = getattr(physical, "exclusion_rule", "")
        if rule:
            nature = "heredada" if physical.exclusion_inherited else "directa"
            return f"{path}  (exclusión {nature}: {rule})"
        return path

    def _populate_tree(self, nodes: list[HierarchyNode]) -> None:
        self.list.clear()
        for node in nodes:
            self.list.addTopLevelItem(self._make_item(node))
        for index in range(self.list.topLevelItemCount()):
            self._apply_expansion(self.list.topLevelItem(index))

    def _apply_expansion(self, item: QTreeWidgetItem) -> None:
        node = item.data(0, Qt.UserRole + 3)
        if node is not None:
            item.setExpanded(node.default_expanded)
        for index in range(item.childCount()):
            self._apply_expansion(item.child(index))

    def _make_item(self, node: HierarchyNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node.label])
        item.setData(0, Qt.UserRole, node.entry)
        item.setData(0, Qt.UserRole + 2, node.is_unassigned)
        item.setData(0, Qt.UserRole + 3, node)
        item.setToolTip(0, node.tooltip)
        if node.icon:
            item.setIcon(0, icons.icon(node.icon))
        key = self._copy_key(node.entry, self._eligible_keys)
        if key is not None:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole + 1, key)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        if node.is_section:
            item.setFlags(Qt.NoItemFlags)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
        elif node.entry is None:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        if node.is_unassigned:
            from gipler.gui.theme import load_preference, semantic

            item.setForeground(0, QColor(semantic(load_preference(), "new_in_dev")))
        for child in node.children:
            item.addChild(self._make_item(child))
        return item

    def _copy_key(self, entry, eligible_keys: set[tuple[str, str]] | None = None):
        if entry is None:
            return None
        key = selection_key_for_entry(entry)
        if key is None:
            return None
        if eligible_keys is not None and key not in eligible_keys:
            return None
        return key

    def _copy_check_changed(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if self._syncing_checks:
            return
        key = item.data(0, Qt.UserRole + 1)
        if key is not None:
            self.copy_selection_changed.emit(key, item.checkState(0) == Qt.Checked)

    def sync_selection(self, selected: set[tuple[str, str]]) -> None:
        self._syncing_checks = True

        def visit(item: QTreeWidgetItem) -> None:
            key = item.data(0, Qt.UserRole + 1)
            if key is not None:
                item.setCheckState(
                    0, Qt.Checked if key in selected else Qt.Unchecked
                )
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.list.topLevelItemCount()):
            visit(self.list.topLevelItem(index))
        self._syncing_checks = False

    def _filter(self, text: str) -> None:
        needle = text.casefold()
        visible = 0
        for index in range(self.list.topLevelItemCount()):
            if self._filter_item(self.list.topLevelItem(index), needle):
                visible += 1
        if self.list.topLevelItemCount():
            self.empty_label.setText("Sin resultados")
            self.empty_label.setVisible(visible == 0)
        if self.list.topLevelItemCount() and visible:
            self.list.setVisible(True)

    def _filter_item(self, item: QTreeWidgetItem, needle: str) -> bool:
        node = item.data(0, Qt.UserRole + 3)
        own_match = bool(needle) and (
            needle in getattr(node, "path", "").casefold()
            or needle in getattr(node, "label", "").casefold()
        )
        child_visible = False
        for index in range(item.childCount()):
            if self._filter_item(item.child(index), needle):
                child_visible = True
        shown = not needle or own_match or child_visible
        item.setHidden(not shown)
        if needle and shown and child_visible:
            item.setExpanded(True)
        return shown

    def current_node(self) -> HierarchyNode | None:
        item = self.list.currentItem()
        return item.data(0, Qt.UserRole + 3) if item else None

    def current_entry(self):
        node = self.current_node()
        return node.entry if node is not None else None

    def _selection_changed(self) -> None:
        node = self.current_node()
        entry = node.entry if node is not None else None
        self.selected.emit(entry)
        if self.mode == "excluded":
            self.restore_button.setEnabled(
                bool(node is not None and node.restorable)
            )
        elif self.mode == "indeterminate":
            self.rule_button.setEnabled(self._can_create_rule(entry))

    def _activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        entry = item.data(0, Qt.UserRole)
        if entry is not None:
            self.activated.emit(entry)

    def _restore(self) -> None:
        node = self.current_node()
        if node is not None and node.restorable:
            self.restore_requested.emit(node.entry)

    def _create_rule(self) -> None:
        entry = self.current_entry()
        if self._can_create_rule(entry):
            self.rule_requested.emit(entry)

    @staticmethod
    def _can_create_rule(entry) -> bool:
        if not isinstance(entry, ProfileEntry):
            return False
        return entry.membership.state in (
            MembershipState.UNKNOWN,
            MembershipState.AMBIGUOUS,
        )

    def _open_context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if item is None:
            return
        menu = self.context_menu_for(item)
        if menu is None:
            return
        self.list.setCurrentItem(item)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def context_menu_for(self, item: QTreeWidgetItem | None) -> QMenu | None:
        entry = item.data(0, Qt.UserRole) if item is not None else None
        if entry is None:
            return None
        menu = QMenu(self)
        menu.addAction("Seleccionar").triggered.connect(
            lambda: self.selected.emit(entry)
        )
        menu.addAction("Abrir en explorador").triggered.connect(
            lambda: self.explorer_requested.emit(entry)
        )
        if self.mode == "indeterminate" and self._can_assign(item, entry):
            if self._targets:
                submenu = menu.addMenu("Asignar a")
                for source_id, name in self._targets:
                    action = submenu.addAction(name)
                    action.triggered.connect(
                        lambda _checked=False, s=source_id, e=entry: self.assign_requested.emit(e, s)
                    )
        if self.mode != "excluded":
            menu.addAction("Excluir").triggered.connect(
                lambda: self.exclude_requested.emit(entry)
            )
        if self.mode == "indeterminate" and self._can_create_rule(entry):
            menu.addAction("Crear regla para seleccionado").triggered.connect(
                lambda: self.rule_requested.emit(entry)
            )
        return menu

    @staticmethod
    def _is_unassigned(item: QTreeWidgetItem | None, entry) -> bool:
        if item is not None and item.data(0, Qt.UserRole + 2):
            return True
        return bool(getattr(entry, "is_unassigned_new", False))

    @classmethod
    def _can_assign(cls, item: QTreeWidgetItem | None, entry) -> bool:
        """Permite asignar archivos nuevos sin referencia y pertenencias
        compartidas. La asignación explícita resuelve la membresía múltiple
        sin cambiar el comportamiento de UNKNOWN ni AMBIGUOUS."""
        if cls._is_unassigned(item, entry):
            return True
        membership = getattr(entry, "membership", None)
        return (
            membership is not None
            and membership.state == MembershipState.SHARED
        )


class ProfileLauncherDialog(QDialog):
    """Choose, create, or manage profiles from the main window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Abrir espacio de trabajo de Gipler")
        apply_window_icon(self)
        self.setMinimumWidth(440)
        self.profile_id: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Seleccione un espacio de trabajo o cree uno nuevo.")
        )
        self.profiles = QComboBox()
        layout.addWidget(self.profiles)
        row = QHBoxLayout()
        self.create_button = QPushButton("Crear espacio de trabajo…")
        self.open_button = QPushButton("Abrir")
        self.delete_button = QPushButton("Eliminar…")
        row.addWidget(self.create_button)
        row.addWidget(self.open_button)
        row.addWidget(self.delete_button)
        layout.addLayout(row)
        self.create_button.clicked.connect(self._create)
        self.open_button.clicked.connect(self._open)
        self.delete_button.clicked.connect(self._delete)
        self.profiles.currentIndexChanged.connect(self._update_buttons)
        self._refresh_profiles()

    def _refresh_profiles(self, selected: str | None = None) -> None:
        self.profiles.clear()
        for profile in list_profiles():
            self.profiles.addItem(profile.name, profile.id)
        index = self.profiles.findData(selected)
        if index < 0:
            last_id = None
            try:
                from gipler.profile import last_profile_id

                last_id = last_profile_id()
            except ProfileError:
                last_id = None
            index = self.profiles.findData(last_id)
        self.profiles.setCurrentIndex(index if index >= 0 else 0)
        self._update_buttons()

    def _update_buttons(self, *_args) -> None:
        has_profile = bool(self.profiles.currentData())
        self.open_button.setEnabled(has_profile)
        self.delete_button.setEnabled(has_profile)

    def _create(self) -> None:
        name, accepted = QInputDialog.getText(
            self, "Nuevo espacio de trabajo", "Nombre del espacio de trabajo:"
        )
        if not accepted:
            return
        work_dir = QFileDialog.getExistingDirectory(self, "Directorio de trabajo")
        if not work_dir:
            return
        try:
            profile = create_profile(name, work_dir)
            set_last_profile_id(profile.id)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(
                self, "No se pudo crear el espacio de trabajo", str(exc)
            )
            return
        self.profile_id = profile.id
        self.accept()

    def _open(self) -> None:
        self.profile_id = self.profiles.currentData()
        if self.profile_id:
            set_last_profile_id(self.profile_id)
            self.accept()

    def _delete(self) -> None:
        profile_id = self.profiles.currentData()
        if not profile_id:
            return
        answer = QMessageBox.question(
            self,
            "Eliminar espacio de trabajo",
            "¿Eliminar el espacio de trabajo y su configuración? No se borrarán los archivos "
            "del directorio de trabajo ni de las fuentes.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_profile(profile_id)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(
                self, "No se pudo eliminar el espacio de trabajo", str(exc)
            )
            return
        self._refresh_profiles()


class SourceDialog(QDialog):
    def __init__(
        self,
        source: Source | None = None,
        parent=None,
        sources: list[Source] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            "Editar directorio de sincronización"
            if source is not None
            else "Agregar directorio de sincronización"
        )
        apply_window_icon(self)
        self.source = source
        self._initial_alternative = bool(
            source
            and source.sync_destination
            and os.path.normcase(
                os.path.abspath(os.path.expanduser(source.sync_destination))
            )
            != os.path.normcase(os.path.abspath(os.path.expanduser(source.root)))
        )
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(source.name if source else "")
        self.name.setToolTip("Nombre identificativo que aparecerá en la pestaña.")
        self.root = QLineEdit(source.root if source else "")
        self.root.setToolTip(
            "Directorio físico que Gipler compara con el directorio de trabajo."
        )
        browse = QPushButton("Examinar…")
        browse.clicked.connect(self._browse)
        root_row = QHBoxLayout()
        root_row.addWidget(self.root)
        root_row.addWidget(browse)
        self.sync_enabled = QCheckBox(
            "Comparar y sincronizar con este directorio"
        )
        self.sync_enabled.setChecked(
            source.sync_enabled if source is not None else True
        )
        self.sync_enabled.setToolTip(
            "Permite preparar operaciones hacia el destino configurado. Selección, "
            "revisión, autorización y ejecución siguen siendo pasos separados."
        )
        form.addRow("Nombre", self.name)
        form.addRow("Directorio", root_row)
        form.addRow("", self.sync_enabled)
        layout.addLayout(form)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Opciones avanzadas")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced = QWidget()
        self.advanced.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced)

        recognition_group = QGroupBox("Reconocimiento")
        recognition_form = QFormLayout(recognition_group)
        self.kind = QComboBox()
        self.kind.addItem("Directorio", "reference_directory")
        self.kind.addItem("Reglas", "rules")
        if source is not None and self.kind.findData(source.kind) < 0:
            self.kind.addItem(f"Tipo actual ({source.kind})", source.kind)
        selected = self.kind.findData(source.kind if source else "reference_directory")
        self.kind.setCurrentIndex(max(0, selected))
        self.kind.setToolTip(
            "Directorio: reconoce rutas presentes en la contraparte física. "
            "Reglas: reconoce rutas mediante patrones."
        )
        self.patterns = QLineEdit(
            ", ".join(source.config.get("patterns", [])) if source else ""
        )
        self.patterns.setToolTip(
            "Patrones de rutas para el método Reglas; separar por comas."
        )
        self.exclusive = QCheckBox("Pertenencia exclusiva (conflictos serán ambiguos)")
        self.exclusive.setChecked(bool(source and source.config.get("exclusive", False)))
        self.exclusive.setToolTip(
            "Si varias fuentes reclaman una ruta, marcarla como ambigua en lugar de compartida."
        )
        self.recognizer = QCheckBox("Reconoce pertenencia")
        self.recognizer.setChecked(source.acts_as_recognizer if source else True)
        self.recognizer.setToolTip(
            "Participa en la determinación de pertenencia. Puede reconocer y comparar "
            "sin habilitarse como destino de sincronización."
        )
        self.destination = QCheckBox(
            "Permitir que otras pertenencias se vinculen a este destino"
        )
        self.destination.setChecked(
            source.acts_as_destination if source is not None else True
        )
        self.destination.setToolTip(
            "Permite usar esta fuente como destino de una vinculación configurada en "
            "otra fuente; no habilita operaciones por sí misma."
        )
        recognition_form.addRow("Método", self.kind)
        recognition_form.addRow("", self.recognizer)
        recognition_form.addRow("Patrones", self.patterns)
        recognition_form.addRow("", self.exclusive)
        self.recognition_form = recognition_form
        advanced_layout.addWidget(recognition_group)

        destination_group = QGroupBox("Destino de sincronización")
        destination_form = QFormLayout(destination_group)
        self.alternative_destination = QCheckBox(
            "Usar un directorio de destino diferente"
        )
        self.alternative_destination.setChecked(self._initial_alternative)
        self.alternative_destination.setToolTip(
            "De forma predeterminada se utiliza el directorio de comparación. "
            "Active esto solo para separar el destino físico."
        )
        self.sync_path = QLineEdit(source.sync_destination if source else "")
        self.sync_path.setToolTip("Directorio físico alternativo que recibirá las operaciones.")
        self.sync_path_browse = QPushButton("Examinar…")
        self.sync_path_browse.clicked.connect(self._browse_sync_destination)
        self.sync_path_row = QWidget()
        sync_path_layout = QHBoxLayout(self.sync_path_row)
        sync_path_layout.setContentsMargins(0, 0, 0, 0)
        sync_path_layout.addWidget(self.sync_path)
        sync_path_layout.addWidget(self.sync_path_browse)
        self.sync_path_row.setVisible(self._initial_alternative)
        self.alternative_destination.toggled.connect(self.sync_path_row.setVisible)
        self.destination_source = QComboBox()
        self.destination_source.setToolTip(
            "Vincula la pertenencia reconocida aquí con otra referencia habilitada "
            "como destino. La selección de operaciones sigue siendo explícita."
        )
        self.destination_source.addItem("Sin destino vinculado", "")
        for candidate in sorted(sources or (), key=lambda item: item.order):
            if candidate.id == (source.id if source else ""):
                continue
            if candidate.is_destination and candidate.sync_destination:
                self.destination_source.addItem(candidate.name, candidate.id)
        if source and source.destination_source_id:
            target_index = self.destination_source.findData(source.destination_source_id)
            if target_index < 0:
                target = next(
                    (
                        item for item in (sources or ())
                        if item.id == source.destination_source_id
                    ),
                    None,
                )
                if target is not None:
                    self.destination_source.addItem(
                        f"{target.name} (configuración actual)", target.id
                    )
                    target_index = self.destination_source.count() - 1
            if target_index >= 0:
                self.destination_source.setCurrentIndex(target_index)
        destination_form.addRow("", self.destination)
        destination_form.addRow("", self.alternative_destination)
        destination_form.addRow("Directorio alternativo", self.sync_path_row)
        destination_form.addRow("Vincular pertenencia con", self.destination_source)
        advanced_layout.addWidget(destination_group)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.kind.currentIndexChanged.connect(self._update_fields)
        self.root.textChanged.connect(self._update_fields)
        self._update_fields()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Seleccionar directorio", self.root.text())
        if selected:
            self.root.setText(selected)
            if not self.name.text().strip() and self.source is None:
                self.name.setText(os.path.basename(os.path.normpath(selected)))

    def _browse_sync_destination(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Seleccionar directorio de destino", self.sync_path.text()
        )
        if selected:
            self.sync_path.setText(selected)

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced.setVisible(expanded)
        self.advanced_toggle.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow
        )

    def _update_fields(self, *_args) -> None:
        is_rules = self.kind.currentData() == "rules"
        self.patterns.setEnabled(is_rules)
        self.exclusive.setEnabled(is_rules)
        self.recognition_form.setRowVisible(self.patterns, is_rules)
        self.exclusive.setVisible(is_rules)
        self.sync_enabled.setEnabled(
            self.kind.currentData() == "reference_directory"
            and bool(self.root.text().strip())
        )

    def configured_source(self) -> Source | None:
        name = self.name.text().strip()
        if not name:
            return None
        existing = self.source
        root_text = self.root.text().strip()
        if self.kind.currentData() == "reference_directory" and not root_text:
            return None
        if self.alternative_destination.isChecked() and not self.sync_path.text().strip():
            return None
        root = os.path.abspath(os.path.expanduser(root_text)) if root_text else ""
        if self.alternative_destination.isChecked():
            sync_destination = os.path.abspath(
                os.path.expanduser(self.sync_path.text().strip())
            )
        elif existing is None:
            sync_destination = root if self.sync_enabled.isChecked() else ""
        elif self._initial_alternative:
            sync_destination = root
        elif existing.sync_destination and (
            os.path.normcase(
                os.path.abspath(os.path.expanduser(existing.sync_destination))
            )
            == os.path.normcase(os.path.abspath(os.path.expanduser(existing.root)))
        ):
            sync_destination = root
        elif self.sync_enabled.isChecked() and not existing.sync_destination:
            sync_destination = root
        else:
            sync_destination = existing.sync_destination
        patterns = [value.strip() for value in self.patterns.text().split(",") if value.strip()]
        config = dict(existing.config) if existing else {}
        if self.kind.currentData() == "rules":
            config["patterns"] = patterns
            config["exclusive"] = self.exclusive.isChecked()
        return Source(
            id=existing.id if existing else new_source_id(),
            name=name,
            kind=self.kind.currentData(),
            root=root,
            enabled=existing.enabled if existing else True,
            order=existing.order if existing else 0,
            acts_as_recognizer=self.recognizer.isChecked(),
            acts_as_destination=self.destination.isChecked(),
            sync_destination=sync_destination,
            sync_enabled=self.sync_enabled.isChecked(),
            destination_source_id=self.destination_source.currentData() or "",
            config=config,
        )


