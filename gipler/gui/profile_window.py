"""Profile lifecycle and dynamic profile workspace navigation."""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gipler.profile import (
    Profile,
    ProfileError,
    Source,
    add_exclusion,
    capture_source_baseline,
    create_profile,
    delete_profile,
    list_profiles,
    load_profile,
    new_source_id,
    remove_exclusion,
    rename_profile,
    save_profile,
    set_last_profile_id,
)
from gipler.profile_analysis import ProfileAnalysis, ProfileEntry, analyze_profile
from gipler.recognition import MembershipState


class EstablishBaselineDialog(QDialog):
    """Explicit, reviewable confirmation of one source's initial state."""

    def __init__(self, profile: Profile, source: Source, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.source = source
        self.other_reference_dirs = tuple(
            dict.fromkeys(
                path
                for existing in profile.sources
                if existing.id != source.id
                for path in (existing.root, existing.sync_destination)
                if path and os.path.isdir(os.path.expanduser(path))
            )
        )
        self.baseline = capture_source_baseline(
            profile.work_dir,
            source.root,
            source.sync_destination or source.root,
            self.other_reference_dirs,
        )
        self.setWindowTitle("Establecer línea de base")
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
                self.other_reference_dirs,
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

    UNASSIGNED_LABEL = "[Nuevo sin asignar]"

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
    ):
        super().__init__(parent)
        self.mode = mode
        self._syncing_checks = False
        self._targets = [(str(source_id), str(name)) for source_id, name in targets]
        self._unassigned = tuple(unassigned or ())
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por ruta…")
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._open_context_menu)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._activate)
        self.empty_label = QLabel(empty_text)
        self.empty_label.setAlignment(Qt.AlignCenter)
        show_unassigned = mode == "indeterminate" and bool(self._unassigned)
        has_items = bool(entries) or show_unassigned
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
        self.search.textChanged.connect(self._filter)
        if show_unassigned:
            self._add_section_header("Archivos nuevos")
            for entry in self._unassigned:
                self._add_unassigned_item(entry)
            if entries:
                self._add_section_header("Otros indeterminados")
        for entry in entries:
            item = QListWidgetItem(self._label(entry))
            item.setData(Qt.UserRole, entry)
            item.setToolTip(getattr(entry, "path", ""))
            key = self._copy_key(entry, eligible_keys)
            if key is not None:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole + 1, key)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            self.list.addItem(item)
        self.list.itemChanged.connect(self._copy_check_changed)
        if disabled:
            self.search.setEnabled(False)
            self.list.setEnabled(False)
            self.empty_label.setText(empty_text)
            self.empty_label.setVisible(True)
            self.action_row.setVisible(False)

    def _add_section_header(self, title: str) -> None:
        item = QListWidgetItem(title)
        item.setFlags(Qt.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.list.addItem(item)

    def _add_unassigned_item(self, entry) -> None:
        from gipler.gui.theme import load_preference, semantic

        item = QListWidgetItem(f"{entry.path}  {self.UNASSIGNED_LABEL}")
        item.setData(Qt.UserRole, entry)
        item.setData(Qt.UserRole + 2, True)
        item.setToolTip("Archivo nuevo aparecido tras la línea de base; sin referencia asignada")
        item.setForeground(QColor(semantic(load_preference(), "new_in_dev")))
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        self.list.addItem(item)

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

    @staticmethod
    def _copy_key(entry, eligible_keys: set[tuple[str, str]] | None = None):
        destination_id = getattr(entry, "eligible_destination_source_id", None)
        if destination_id is None:
            return None
        key = destination_id, entry.path
        if eligible_keys is not None and key not in eligible_keys:
            return None
        return key

    def _copy_check_changed(self, item: QListWidgetItem) -> None:
        if self._syncing_checks:
            return
        key = item.data(Qt.UserRole + 1)
        if key is not None:
            self.copy_selection_changed.emit(key, item.checkState() == Qt.Checked)

    def sync_selection(self, selected: set[tuple[str, str]]) -> None:
        self._syncing_checks = True
        for index in range(self.list.count()):
            item = self.list.item(index)
            key = item.data(Qt.UserRole + 1)
            if key is not None:
                item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)
        self._syncing_checks = False

    def _filter(self, text: str) -> None:
        needle = text.casefold()
        visible = 0
        for index in range(self.list.count()):
            item = self.list.item(index)
            shown = needle in getattr(item.data(Qt.UserRole), "path", "").casefold()
            item.setHidden(not shown)
            visible += int(shown)
        if self.list.count():
            self.empty_label.setText("Sin resultados")
            self.empty_label.setVisible(visible == 0)

    def current_entry(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selection_changed(self) -> None:
        entry = self.current_entry()
        self.selected.emit(entry)
        if self.mode == "excluded":
            self.restore_button.setEnabled(entry is not None)
        elif self.mode == "indeterminate":
            self.rule_button.setEnabled(self._can_create_rule(entry))

    def _activate(self, item: QListWidgetItem) -> None:
        self.activated.emit(item.data(Qt.UserRole))

    def _restore(self) -> None:
        entry = self.current_entry()
        if entry is not None:
            self.restore_requested.emit(entry)

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

    def context_menu_for(self, item: QListWidgetItem | None) -> QMenu | None:
        entry = item.data(Qt.UserRole) if item is not None else None
        if entry is None:
            return None
        menu = QMenu(self)
        menu.addAction("Seleccionar").triggered.connect(
            lambda: self.selected.emit(entry)
        )
        menu.addAction("Abrir en explorador").triggered.connect(
            lambda: self.explorer_requested.emit(entry)
        )
        if self.mode == "indeterminate" and self._is_unassigned(item, entry):
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
    def _is_unassigned(item: QListWidgetItem | None, entry) -> bool:
        if item is not None and item.data(Qt.UserRole + 2):
            return True
        return bool(getattr(entry, "is_unassigned_new", False))


class ProfileLauncherDialog(QDialog):
    """Choose, create, or manage profiles from the main window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Abrir perfil de Gipler")
        self.setMinimumWidth(440)
        self.profile_id: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleccione un perfil o cree uno nuevo."))
        self.profiles = QComboBox()
        layout.addWidget(self.profiles)
        row = QHBoxLayout()
        self.create_button = QPushButton("Crear perfil…")
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
        name, accepted = QInputDialog.getText(self, "Nuevo perfil", "Nombre del perfil:")
        if not accepted:
            return
        work_dir = QFileDialog.getExistingDirectory(self, "Directorio de trabajo")
        if not work_dir:
            return
        try:
            profile = create_profile(name, work_dir)
            set_last_profile_id(profile.id)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo crear el perfil", str(exc))
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
            "Eliminar perfil",
            "¿Eliminar el perfil y su configuración? No se borrarán los archivos "
            "del directorio de trabajo ni de las fuentes.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_profile(profile_id)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo eliminar el perfil", str(exc))
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


class ProfileComparisonPage(QWidget):
    """A reference tab backed by Gipler's shared comparison tree and filters."""

    selected = Signal(object, object)
    activated = Signal(object, object)
    copy_selection_changed = Signal(object, bool)
    exclude_requested = Signal(str)
    search_changed = Signal(str)
    repository_changed = Signal(str)

    def __init__(
        self,
        source: Source,
        rows: tuple,
        entries: tuple,
        dev_root: str,
        reference_root: str,
        eligible_keys: set[tuple[str, str]],
        parent=None,
    ):
        super().__init__(parent)
        from gipler.gui.comparison_view import (
            DEV_HEADERS,
            REPO_HEADERS,
            ComparisonPanel,
            PanelProxy,
        )
        from gipler.gui.models.comparison_tree import ComparisonTreeModel

        self.source = source
        self.entries_by_path = {entry.path: entry for entry in entries}
        self._syncing_selection = False
        self.model = ComparisonTreeModel(list(rows), destination=None, parent=self)
        self.model.eligible_keys = eligible_keys
        self.model.copy_selection_changed.connect(self.copy_selection_changed)
        self.dev_proxy = PanelProxy(DEV_HEADERS, self)
        self.repo_proxy = PanelProxy(REPO_HEADERS, self)
        self.dev_proxy.physical_side = "dev"
        self.dev_proxy.dev_root = dev_root
        self.repo_proxy.physical_side = "repo"
        self.repo_proxy.dev_root = dev_root
        self.repo_proxy.repo_root = reference_root
        self.dev_proxy.setSourceModel(self.model)
        self.repo_proxy.setSourceModel(self.model)
        self.dev_proxy.sort(0, Qt.AscendingOrder)
        self.repo_proxy.sort(0, Qt.AscendingOrder)

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.axis_a = QComboBox()
        self.axis_a.addItems(
            ["todos", "new_in_dev", "modified_in_dev", "identical", "missing_in_dev", "not_comparable", "n/a", "Diferencias"]
        )
        self.axis_a.setCurrentText("Diferencias")
        self.axis_a.setToolTip(
            "Oculta archivos idénticos sin eliminarlos del análisis. Use «identical» "
            "o «todos» para consultarlos."
        )
        self.axis_b = QComboBox()
        self.axis_b.addItems(
            ["todos", "tracked_clean", "tracked_modified", "untracked", "ignored", "n/a"]
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nombre o ruta…")
        self.incidences = QCheckBox("Incidencias")
        self.up_button = QPushButton("Subir")
        self.owner = QComboBox()
        self.owner.addItems(["todos"] + sorted({row.owner for row in rows if row.owner}))
        filters.addWidget(self.axis_a)
        filters.addWidget(self.axis_b)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.incidences)
        filters.addWidget(self.owner)
        filters.addWidget(self.up_button)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.dev_panel = ComparisonPanel("Dev", self)
        directory_title = (
            os.path.basename(os.path.normpath(reference_root)) or source.name
        )
        self.reference_panel = ComparisonPanel(directory_title, self)
        self.reference_panel.set_reference_mode(True)
        self.reference_panel.set_title(directory_title, tooltip=reference_root)
        self.dev_panel.set_model(self.dev_proxy)
        self.reference_panel.set_model(self.repo_proxy)
        self.reference_panel.base_root = reference_root
        self.dev_panel.base_root = dev_root
        self.dev_panel.exclude_requested.connect(self.exclude_requested)
        self.reference_panel.exclude_requested.connect(self.exclude_requested)
        splitter.addWidget(self.dev_panel)
        splitter.addWidget(self.reference_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        from gipler.gui.git_bar import GitBar

        self.git_bar = GitBar(reference_root, self)
        self.git_bar.setEnabled(source.enabled)
        self.git_bar.repository_changed.connect(self.repository_changed)
        self.reference_panel.set_header_extra(self.git_bar, 2)

        self.dev_panel.tree.selectionModel().selectionChanged.connect(
            lambda selected, deselected: self._sync_current(
                self.dev_panel, self.dev_proxy, self.reference_panel, self.repo_proxy,
                selected, deselected,
            )
        )
        self.reference_panel.tree.selectionModel().selectionChanged.connect(
            lambda selected, deselected: self._sync_current(
                self.reference_panel, self.repo_proxy, self.dev_panel, self.dev_proxy,
                selected, deselected,
            )
        )
        self.dev_panel.tree.doubleClicked.connect(
            lambda index: self._activate(self.dev_panel, self.dev_proxy, index)
        )
        self.reference_panel.tree.doubleClicked.connect(
            lambda index: self._activate(self.reference_panel, self.repo_proxy, index)
        )
        self.axis_a.currentTextChanged.connect(self._apply_filters)
        self.axis_b.currentTextChanged.connect(self._apply_filters)
        self.search.textChanged.connect(self._apply_filters)
        self.search.textChanged.connect(self.search_changed)
        self.incidences.toggled.connect(self._apply_filters)
        self.owner.currentTextChanged.connect(self._apply_filters)
        self.up_button.clicked.connect(self.go_up)
        self._apply_filters()
        self.expand_changes()

    def _apply_filters(self, *_args) -> None:
        axis_a = self.axis_a.currentText()
        differences_only = axis_a.casefold() == "diferencias"
        criteria = {
            "axis_a": None if axis_a == "todos" or differences_only else axis_a,
            "axis_b": None if self.axis_b.currentText() == "todos" else self.axis_b.currentText(),
            "incidences": self.incidences.isChecked(),
            "search": self.search.text(),
            "owner": "" if self.owner.currentText() == "todos" else self.owner.currentText(),
            "exclude_identical": differences_only,
        }
        self.dev_proxy.set_criteria(**criteria)
        self.repo_proxy.set_criteria(**criteria)
        self.expand_changes()

    def go_up(self) -> None:
        for panel in (self.dev_panel, self.reference_panel):
            root = panel.tree.rootIndex()
            if root.isValid():
                panel.tree.setRootIndex(root.parent())

    def expand_changes(self) -> None:
        from PySide6.QtCore import QModelIndex

        relevant = {"new_in_dev", "modified_in_dev", "missing_in_dev", "not_comparable"}
        for panel, proxy in (
            (self.dev_panel, self.dev_proxy),
            (self.reference_panel, self.repo_proxy),
        ):
            ancestors: dict[str, QModelIndex] = {}

            def visit(parent_index: QModelIndex) -> None:
                for index in range(proxy.rowCount(parent_index)):
                    proxy_index = proxy.index(index, 0, parent_index)
                    source_index = proxy.mapToSource(proxy_index)
                    node = self.model.node_at(source_index)
                    if node.row is not None and (
                        node.row.axis_a in relevant or node.row.incidences
                    ):
                        ancestor = source_index.parent()
                        while ancestor.isValid():
                            parent_node = self.model.node_at(ancestor)
                            ancestors[parent_node.path] = ancestor
                            ancestor = ancestor.parent()
                    if node.is_dir:
                        visit(proxy_index)

            visit(QModelIndex())
            for source_index in ancestors.values():
                proxy_index = proxy.mapFromSource(source_index)
                if proxy_index.isValid() and proxy.rowCount(proxy_index):
                    panel.tree.expand(proxy_index)

    def _sync_current(self, source_panel, source_proxy, target_panel, target_proxy, selected, _deselected):
        if self._syncing_selection or not selected:
            return
        indexes = [index for index in selected.indexes() if index.column() == 0]
        if not indexes:
            return
        index = indexes[0]
        source_index = source_proxy.mapToSource(index)
        node = self.model.node_at(source_index)
        entry = self.entries_by_path.get(node.path)
        self.selected.emit(entry, self.source.id)
        self._syncing_selection = True
        target_index = target_proxy.mapFromSource(source_index)
        if target_index.isValid():
            from PySide6.QtCore import QItemSelectionModel

            target_panel.tree.selectionModel().setCurrentIndex(
                target_index,
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
            )
        self._syncing_selection = False

    def _activate(self, panel, proxy, index) -> None:
        source_index = proxy.mapToSource(index)
        node = self.model.node_at(source_index)
        if node.is_dir:
            for other_panel, other_proxy in (
                (self.dev_panel, self.dev_proxy),
                (self.reference_panel, self.repo_proxy),
            ):
                other_panel.tree.setRootIndex(other_proxy.mapFromSource(source_index))
            return
        if node.row is not None:
            self.activated.emit(node.row, self.source.id)

    def sync_selection(self, selected: set[tuple[str, str]]) -> None:
        self.model.checked_keys = selected

        def notify(parent_index) -> None:
            for index in range(self.model.rowCount(parent_index)):
                source_index = self.model.index(index, 0, parent_index)
                self.model.dataChanged.emit(
                    source_index, source_index, [Qt.CheckStateRole]
                )
                notify(source_index)

        notify(self.model.index(-1, 0))


class ProfileWindow(QMainWindow):
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.analysis: ProfileAnalysis | None = None
        self._source_pages: dict[str, ProfileComparisonPage] = {}
        self._eligible_copy_keys: set[tuple[str, str]] = set()
        from gipler.gui.selection import SelectionController

        self.selection_ctrl = SelectionController()
        self.ops_cache: list = []
        self.is_executing = False
        self._copy_thread = None
        self._copy_worker = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setWindowTitle(f"Gipler — {self.profile.name}")
        self.resize(1280, 820)
        toolbar = QWidget()
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 4, 8, 4)
        self.profile_label = QLabel(f"Perfil: {self.profile.name}")
        row.addWidget(self.profile_label)
        row.addWidget(QLabel(self.profile.work_dir), 1)
        from gipler.gui.theme import apply_theme

        self.theme_selector = QComboBox()
        self.theme_selector.addItem("Oscuro", "oscuro")
        self.theme_selector.addItem("Claro", "claro")
        theme = self.profile.view.get("theme", "oscuro")
        self.theme_selector.setCurrentIndex(max(0, self.theme_selector.findData(theme)))
        self.theme_selector.currentIndexChanged.connect(self._set_theme)
        row.addWidget(QLabel("Apariencia:"))
        row.addWidget(self.theme_selector)
        apply_theme(theme)
        rename_button = QPushButton("Renombrar")
        work_button = QPushButton("Cambiar directorio")
        close_button = QPushButton("Cerrar perfil")
        delete_button = QPushButton("Eliminar perfil…")
        rename_button.clicked.connect(self._rename_profile)
        work_button.clicked.connect(self._change_work_dir)
        close_button.clicked.connect(self.close)
        delete_button.clicked.connect(self._delete_profile)
        for button in (rename_button, work_button, close_button, delete_button):
            row.addWidget(button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(toolbar)
        self.tabs = QTabWidget()
        self.tabs.setMovable(False)
        self.tabs.setTabsClosable(False)
        layout.addWidget(self.tabs, 1)
        from gipler.gui.inspector import Inspector

        self.inspector = Inspector(self)
        self.inspector.setMaximumHeight(260)
        layout.addWidget(self.inspector)
        actions = QHBoxLayout()
        self.btn_safe = QPushButton("Selección segura")
        self.btn_prepare = QPushButton("Preparar operaciones")
        self.btn_execute = QPushButton("Ejecutar copia (0)")
        self.btn_execute.setEnabled(False)
        self.btn_safe.clicked.connect(self.select_safe_visible)
        self.btn_prepare.clicked.connect(lambda: self.prepare_operations(show_dialog=True))
        self.btn_execute.clicked.connect(self._execute_prepared)
        actions.addWidget(self.btn_safe)
        actions.addWidget(self.btn_prepare)
        actions.addWidget(self.btn_execute)
        layout.addLayout(actions)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Perfil abierto")
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def refresh(self) -> None:
        try:
            self.profile = load_profile(self.profile.id)
            self.analysis = analyze_profile(self.profile)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "Error al analizar el perfil", str(exc))
            return
        from gipler.copy_engine import build_operations

        candidates = self.analysis.copy_rows()
        all_keys = {(row.destination, row.path) for row in candidates}
        operations = build_operations(
            candidates,
            all_keys,
            self.profile.work_dir,
            self.analysis.destination_roots,
            self.analysis.snapshot,
        )
        self._eligible_copy_keys = {
            (operation.destination, operation.path)
            for operation in operations
            if operation.status == "copiable"
        }
        self.selection_ctrl.keys.intersection_update(self._eligible_copy_keys)
        self.ops_cache = []
        self._rebuild_tabs()

    def _rebuild_tabs(self) -> None:
        for old_page in self._source_pages.values():
            old_page.git_bar.deactivate()
            old_page.git_bar.controller.shutdown()
        self.tabs.blockSignals(True)
        self.tabs.clear()
        self._source_pages.clear()
        self.tabs.addTab(
            self._create_page(
                self.analysis.entries,
                "El directorio de trabajo está vacío.",
                eligible_keys=self._eligible_copy_keys,
            ),
            "Inicio",
        )
        self.tabs.widget(0).view_key = "inicio"
        self.tabs.widget(0).search.setText(
            str(self.profile.view.get("search_inicio", ""))
        )
        for source in sorted(self.profile.sources, key=lambda item: item.order):
            entries = self.analysis.source_entries.get(source.id, ())
            reference_root = self.analysis.comparison_roots.get(
                source.id, self.analysis.destination_roots.get(source.id, "")
            )
            page = ProfileComparisonPage(
                source,
                self.analysis.rows_by_source.get(source.id, ()),
                entries,
                self.profile.work_dir,
                reference_root,
                self._eligible_copy_keys,
                self,
            )
            page.setEnabled(source.enabled)
            page.view_key = f"source:{source.id}"
            page.search.setText(
                str(self.profile.view.get(f"search_{page.view_key}", ""))
            )
            page.git_bar.message.connect(self.statusBar().showMessage)
            page.repository_changed.connect(self._git_repository_changed)
            page.add_source_actions = QWidget()
            actions = QHBoxLayout(page.add_source_actions)
            actions.setContentsMargins(0, 0, 0, 0)
            configure = QPushButton("Configurar fuente")
            up = QPushButton("Subir")
            down = QPushButton("Bajar")
            toggle = QPushButton("Activar" if not source.enabled else "Desactivar")
            remove = QPushButton("Eliminar fuente…")
            configure.clicked.connect(lambda _checked=False, sid=source.id: self._edit_source(sid))
            up.clicked.connect(lambda _checked=False, sid=source.id: self._move_source(sid, -1))
            down.clicked.connect(lambda _checked=False, sid=source.id: self._move_source(sid, 1))
            toggle.clicked.connect(lambda _checked=False, sid=source.id: self._toggle_source(sid))
            remove.clicked.connect(lambda _checked=False, sid=source.id: self._remove_source(sid))
            for button in (configure, up, down, toggle, remove):
                actions.addWidget(button)
            page.layout().insertWidget(0, page.add_source_actions)
            self._source_pages[source.id] = page
            label = source.name if source.enabled else f"{source.name} (desactivada)"
            self.tabs.addTab(page, label)
            page.selected.connect(
                lambda entry, source_id: self._inspect_entry(entry, source_id)
            )
            page.activated.connect(self._activate_source_row)
            page.copy_selection_changed.connect(self._copy_selection_changed)
            page.exclude_requested.connect(self._exclude_path)
            page.search_changed.connect(
                lambda text, key=page.view_key: self._save_search(key, text)
            )

        excluded_page = self._create_page(
            self.analysis.inventory.excluded,
            "Ningún archivo excluido",
            mode="excluded",
        )
        excluded_page.view_key = "excluidos"
        excluded_page.search.setText(
            str(self.profile.view.get("search_excluidos", ""))
        )
        self.tabs.addTab(excluded_page, "Excluidos")
        excluded_page.restore_requested.connect(self._restore_exclusion)

        indeterminate_page = self._create_page(
            self.analysis.membership_review_entries,
            "Ningún archivo indeterminado",
            mode="indeterminate",
        )
        indeterminate_page.view_key = "indeterminados"
        indeterminate_page.search.setText(
            str(self.profile.view.get("search_indeterminados", ""))
        )
        self.tabs.addTab(indeterminate_page, "Indeterminados")
        indeterminate_page.rule_requested.connect(self._create_rule_for_entry)

        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if isinstance(page, ProfileListPage):
                page.selected.connect(self._inspect_entry)
                page.activated.connect(lambda entry, idx=index: self._activate_entry(entry, idx))
                page.copy_selection_changed.connect(self._copy_selection_changed)
                page.exclude_requested.connect(
                    lambda entry: self._exclude_path(entry.path)
                )
                page.explorer_requested.connect(self._open_work_item_in_explorer)
                page.sync_selection(self.selection_ctrl.keys)
                page.search.textChanged.connect(
                    lambda text, key=page.view_key: self._save_search(key, text)
                )
            elif isinstance(page, ProfileComparisonPage):
                page.sync_selection(self.selection_ctrl.keys)
        self._restore_active_tab()
        self.tabs.blockSignals(False)
        self._activate_git_bar(self.tabs.currentIndex())
        self.setWindowTitle(f"Gipler — {self.profile.name}")
        self.profile_label.setText(f"Perfil: {self.profile.name}")

    def _create_page(
        self,
        entries,
        empty_text: str,
        mode="inventory",
        disabled=False,
        eligible_keys: set[tuple[str, str]] | None = None,
    ):
        return ProfileListPage(
            entries,
            empty_text,
            mode,
            disabled,
            eligible_keys,
            self,
        )

    def _restore_active_tab(self) -> None:
        active = str(self.profile.view.get("active_tab", "inicio"))
        index = 0
        if active.startswith("source:"):
            source_id = active.split(":", 1)[1]
            for i, source in enumerate(sorted(self.profile.sources, key=lambda item: item.order), 1):
                if source.id == source_id:
                    index = i
                    break
        elif active == "excluidos":
            index = self.tabs.count() - 2
        elif active == "indeterminados":
            index = self.tabs.count() - 1
        if index == 0 and active != "inicio":
            self.profile.view["active_tab"] = "inicio"
            save_profile(self.profile)
        self.tabs.setCurrentIndex(max(0, min(index, self.tabs.count() - 1)))

    def _save_active_tab(self, index: int) -> None:
        if index < 0 or self.analysis is None:
            return
        source_index = index - 1
        if 0 <= source_index < len(self.profile.sources):
            active = "source:" + sorted(self.profile.sources, key=lambda item: item.order)[source_index].id
        elif index == self.tabs.count() - 2:
            active = "excluidos"
        elif index == self.tabs.count() - 1:
            active = "indeterminados"
        else:
            active = "inicio"
        self.profile.view["active_tab"] = active
        save_profile(self.profile)

    def _on_tab_changed(self, index: int) -> None:
        self._save_active_tab(index)
        self._activate_git_bar(index)

    def _activate_git_bar(self, index: int) -> None:
        for page_index in range(self.tabs.count()):
            page = self.tabs.widget(page_index)
            if isinstance(page, ProfileComparisonPage):
                page.git_bar.deactivate()
        if index <= 0 or index > len(self.profile.sources):
            return
        page = self.tabs.widget(index)
        if (
            isinstance(page, ProfileComparisonPage)
            and page.isEnabled()
            and page.git_bar.isEnabled()
        ):
            page.git_bar.activate()

    def _git_repository_changed(self, repository: str) -> None:
        self.statusBar().showMessage(
            "Repositorio Git actualizado; recalculando la comparación…"
        )
        self.refresh()

    def _inspect_entry(self, entry, source_id: str | None = None) -> None:
        from gipler.gui.inspector import Inspector
        from gipler.report import Row

        if entry is None:
            self.inspector.summary.clear()
            self.inspector.info.clear()
            self.inspector.diff.set_texts("", "")
            return
        physical = getattr(entry, "physical", entry)
        path = physical.path
        if isinstance(entry, ProfileEntry) and source_id is None:
            candidates = [
                candidate for candidate in entry.membership.source_ids
                if candidate in self.analysis.comparison_roots
                if any(
                    row.path == path
                    for row in self.analysis.rows_by_source.get(candidate, ())
                )
            ]
            if len(candidates) == 1:
                source_id = candidates[0]
            elif not candidates and entry.membership.destination_source_id:
                target_id = entry.membership.destination_source_id
                if target_id in self.analysis.destination_roots:
                    source_id = target_id
        selected_row = next(
            (
                row for row in self.analysis.rows_by_source.get(source_id, ())
                if row.path == path
            ),
            None,
        ) if source_id else None
        reference_root = (
            self.analysis.comparison_roots.get(source_id)
            or self.analysis.destination_roots.get(source_id, "")
        ) if source_id else ""
        if selected_row is None:
            selected_row = Row(path, "", "sin determinar", "n/a", "n/a", [])
            reference_root = ""
        self.inspector.show_file(
            selected_row, self.profile.work_dir, reference_root
        )
        if isinstance(entry, ProfileEntry):
            summary = self.inspector.summary.toPlainText()
            summary += (
                f"\nPertenencia: {entry.membership.state.value}"
                f"\nFuentes: {', '.join(entry.membership.source_ids) or 'ninguna'}"
                f"\nMotivos: {', '.join(entry.membership.reasons) or 'ninguno'}"
                f"\nComparaciones: "
                + (
                    ", ".join(
                        f"{reference_id}={state}"
                        for reference_id, state in entry.comparisons.items()
                    )
                    or "sin contraparte"
                )
            )
            if entry.destination_comparisons:
                summary += "\nComparaciones de destino: " + ", ".join(
                    f"{destination_id}={state} "
                    f"(Git={entry.destination_git_states.get(destination_id, 'n/a')})"
                    for destination_id, state in entry.destination_comparisons.items()
                )
            self.inspector.summary.setPlainText(summary)
            info = self.inspector.info.toPlainText()
            for destination_id in entry.membership.destination_source_ids:
                source = self.profile.source(destination_id)
                root = self.analysis.destination_roots.get(destination_id, "")
                if source is None or not root or root == reference_root:
                    continue
                destination_path = os.path.join(root, *path.split("/"))
                info += (
                    f"\n\n[Destino «{source.name}»]\n"
                    f"Ruta: {destination_path}\n"
                    + Inspector._fmt(Inspector._meta(destination_path))
                )
            self.inspector.info.setPlainText(info)
        if physical.exclusion_rule:
            nature = "heredada" if physical.exclusion_inherited else "directa"
            self.inspector.summary.appendPlainText(
                f"Exclusión {nature}: {physical.exclusion_rule}"
            )
        self.inspector.tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"Inspección: {path}")

    def _activate_entry(self, entry, tab_index: int) -> None:
        if not isinstance(entry, ProfileEntry) or entry.kind == "directory":
            return
        source_id = None
        if tab_index > 0 and tab_index <= len(self.profile.sources):
            source_id = sorted(self.profile.sources, key=lambda item: item.order)[tab_index - 1].id
        if source_id is None:
            candidates = [
                candidate for candidate in entry.membership.source_ids
                if candidate in self.analysis.comparison_roots
                if candidate in self.analysis.rows_by_source
                and any(
                    row.path == entry.path
                    for row in self.analysis.rows_by_source[candidate]
                )
            ]
            if len(candidates) != 1:
                target_id = entry.membership.destination_source_id
                if not candidates and target_id in self.analysis.destination_roots:
                    source_id = target_id
                else:
                    self.statusBar().showMessage(
                        "Seleccione una fuente para comparar este elemento compartido o ambiguo."
                    )
                    return
            else:
                source_id = candidates[0]
        source = self.profile.source(source_id)
        source_root = (
            self.analysis.comparison_roots.get(source_id)
            or self.analysis.destination_roots.get(source_id, "")
        ) if source else ""
        if source is None or not source_root or not os.path.isdir(source_root):
            self.statusBar().showMessage("La fuente no tiene una contraparte física disponible.")
            return
        from gipler.gui.comparison_window import ComparisonWindow
        row = next(
            row for row in self.analysis.rows_by_source[source_id]
            if row.path == entry.path
        )
        window = ComparisonWindow(row, self.profile.work_dir, source_root, self)
        window.show()
        if not hasattr(self, "_comparison_windows"):
            self._comparison_windows = []
        self._comparison_windows.append(window)

    def _activate_source_row(self, row, source_id: str) -> None:
        source_root = (
            self.analysis.comparison_roots.get(source_id)
            or self.analysis.destination_roots.get(source_id, "")
        )
        if not source_root or not os.path.isdir(source_root):
            self.statusBar().showMessage(
                "La fuente no tiene un directorio de referencia disponible."
            )
            return
        from gipler.gui.comparison_window import ComparisonWindow

        window = ComparisonWindow(row, self.profile.work_dir, source_root, self)
        window.show()
        if not hasattr(self, "_comparison_windows"):
            self._comparison_windows = []
        self._comparison_windows.append(window)

    def _exclude_path(self, relative_path: str) -> None:
        is_directory = os.path.isdir(
            os.path.join(self.profile.work_dir, *relative_path.split("/"))
        )
        pattern = relative_path.rstrip("/") + ("/" if is_directory else "")
        try:
            add_exclusion(self.profile.id, pattern)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo excluir", str(exc))
            return
        self.refresh()

    def _open_work_item_in_explorer(self, entry) -> None:
        physical = getattr(entry, "physical", entry)
        path = os.path.join(self.profile.work_dir, *physical.path.split("/"))
        if physical.kind == "directory":
            target = os.path.abspath(path)
        else:
            target = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(target):
            self.statusBar().showMessage(
                f"No existe el directorio que contiene el elemento: {target}"
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(target)):
            self.statusBar().showMessage(f"No se pudo abrir: {target}")

    def _edit_source(self, source_id: str) -> None:
        source = self.profile.source(source_id)
        if source is None:
            return
        dialog = SourceDialog(source, self, self.profile.sources)
        if not dialog.exec():
            return
        updated = dialog.configured_source()
        if updated is None:
            QMessageBox.warning(
                self,
                "Configuración incompleta",
                "Indique un nombre y un directorio para comparar.",
            )
            return
        root_changed = (
            source.kind != updated.kind
            or os.path.normcase(os.path.abspath(os.path.expanduser(source.root)))
            != os.path.normcase(os.path.abspath(os.path.expanduser(updated.root)))
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
            self.profile, updated, self
        ):
            return
        # Preserve the source object identity and current position.
        source.name = updated.name
        source.kind = updated.kind
        source.root = updated.root
        source.acts_as_recognizer = updated.acts_as_recognizer
        source.acts_as_destination = updated.acts_as_destination
        source.sync_destination = updated.sync_destination
        source.sync_enabled = updated.sync_enabled
        source.destination_source_id = updated.destination_source_id
        source.config = updated.config
        if establish_new_baseline:
            source.baseline = updated.baseline
        try:
            save_profile(self.profile)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo guardar la fuente", str(exc))
            return
        self.refresh()

    def _move_source(self, source_id: str, delta: int) -> None:
        source = self.profile.source(source_id)
        if source is None:
            return
        new_order = max(0, min(source.order + delta, len(self.profile.sources) - 1))
        if new_order == source.order:
            return
        self.profile.reorder_source(source_id, new_order)
        save_profile(self.profile)
        self.refresh()

    def _toggle_source(self, source_id: str) -> None:
        source = self.profile.source(source_id)
        if source is None:
            return
        source.enabled = not source.enabled
        save_profile(self.profile)
        self.refresh()

    def _remove_source(self, source_id: str) -> None:
        source = self.profile.source(source_id)
        if source is None:
            return
        answer = QMessageBox.question(
            self,
            "Eliminar fuente",
            f"¿Retirar «{source.name}» del perfil? No se modificarán sus archivos.",
        )
        if answer != QMessageBox.Yes:
            return
        self.profile.remove_source(source_id)
        save_profile(self.profile)
        self.refresh()

    def _restore_exclusion(self, entry) -> None:
        physical = entry
        rule = physical.exclusion_rule
        if not rule:
            return
        if physical.exclusion_inherited or physical.is_directory:
            answer = QMessageBox.question(
                self,
                "Restaurar exclusión",
                f"Esta regla puede restaurar también otros elementos: {rule}\n"
                "¿Retirar la regla del perfil?",
            )
            if answer != QMessageBox.Yes:
                return
        try:
            remove_exclusion(self.profile.id, rule)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo restaurar", str(exc))
            return
        self.refresh()

    def _create_rule_for_entry(self, entry) -> None:
        path = entry.path
        name, accepted = QInputDialog.getText(
            self, "Reconocer mediante regla", "Nombre de la nueva fuente:"
        )
        if not accepted or not name.strip():
            return
        source = Source(
            id=new_source_id(),
            name=name.strip(),
            kind="rules",
            order=self.profile.next_source_order(),
            config={
                "patterns": [path, path + "/"] if entry.kind == "directory" else [path]
            },
        )
        self.profile.add_source(source)
        save_profile(self.profile)
        self.refresh()
        index = next(
            (i for i, item in enumerate(self.profile.sources) if item.id == source.id), 0
        )
        self.tabs.setCurrentIndex(index + 1)

    def _copy_selection_changed(self, key: tuple[str, str], checked: bool) -> None:
        if key not in self._eligible_copy_keys:
            return
        if checked:
            self.selection_ctrl.add(key)
        else:
            self.selection_ctrl.discard(key)
        self.ops_cache = []
        self._sync_copy_selection()

    def _save_search(self, view_key: str, text: str) -> None:
        self.profile.view[f"search_{view_key}"] = text
        save_profile(self.profile)

    def _set_theme(self, _index: int) -> None:
        theme = self.theme_selector.currentData()
        if theme not in ("oscuro", "claro"):
            return
        from gipler.gui.theme import apply_theme

        apply_theme(theme)
        self.profile.view["theme"] = theme
        save_profile(self.profile)

    def _sync_copy_selection(self) -> None:
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if isinstance(page, ProfileListPage):
                page.sync_selection(self.selection_ctrl.keys)
            elif isinstance(page, ProfileComparisonPage):
                page.sync_selection(self.selection_ctrl.keys)
        self.btn_execute.setText("Ejecutar copia (0)")
        self.btn_execute.setEnabled(False)
        self.statusBar().showMessage(
            f"Seleccionados para copia: {len(self.selection_ctrl)}; prepare para validar."
        )

    def select_safe_visible(self) -> None:
        if self.analysis is None:
            return
        from gipler.copy_engine import build_operations

        candidates = self.analysis.copy_rows()
        all_keys = {(row.destination, row.path) for row in candidates}
        operations = build_operations(
            candidates,
            all_keys,
            self.profile.work_dir,
            self.analysis.destination_roots,
            self.analysis.snapshot,
        )
        self.selection_ctrl.clear()
        for operation in operations:
            if operation.status == "copiable":
                self.selection_ctrl.add((operation.destination, operation.path))
        self.ops_cache = []
        self._sync_copy_selection()

    def prepare_operations(self, show_dialog: bool = False) -> list:
        if self.analysis is None:
            return []
        from gipler.copy_engine import build_operations

        rows = self.analysis.copy_rows()
        self.ops_cache = build_operations(
            rows,
            set(self.selection_ctrl.keys),
            self.profile.work_dir,
            self.analysis.destination_roots,
            self.analysis.snapshot,
        )
        count = sum(operation.status == "copiable" for operation in self.ops_cache)
        self.btn_execute.setText(f"Ejecutar copia ({count})")
        self.btn_execute.setEnabled(count > 0 and not self.is_executing)
        self.statusBar().showMessage(
            f"Preparación: {count} copiables; {len(self.ops_cache) - count} no copiables."
        )
        if show_dialog:
            from gipler.gui.operations_dialog import OperationsDialog

            dialog = OperationsDialog(self)
            dialog.set_operations(self.ops_cache)
            if dialog.exec() and dialog.accepted_authorization:
                self.authorize_and_execute(self.ops_cache)
        return self.ops_cache

    def _execute_prepared(self) -> None:
        if any(operation.status == "copiable" for operation in self.ops_cache):
            self.authorize_and_execute(self.ops_cache)

    def authorize_and_execute(self, operations: list) -> None:
        if self.is_executing or not any(
            operation.status == "copiable" for operation in operations
        ):
            return
        from PySide6.QtCore import QThread
        from gipler.gui.workers.copy_worker import CopyWorker

        self.is_executing = True
        self.btn_safe.setEnabled(False)
        self.btn_prepare.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self._copy_thread = QThread(self)
        self._copy_worker = CopyWorker(list(operations), authorized=True)
        self._copy_worker.moveToThread(self._copy_thread)
        self._copy_thread.started.connect(self._copy_worker.run)
        self._copy_worker.finished.connect(self._copy_finished)
        self._copy_worker.failed.connect(self._copy_failed)
        self._copy_worker.finished.connect(self._copy_thread.quit)
        self._copy_worker.failed.connect(self._copy_thread.quit)
        self._copy_thread.finished.connect(self._copy_worker.deleteLater)
        self._copy_thread.finished.connect(self._copy_thread.deleteLater)
        self._copy_thread.start()

    def _copy_finished(self, results: list) -> None:
        self.is_executing = False
        copied = sum(result.get("status") == "copiada" for result in results)
        self.statusBar().showMessage(f"Ejecución terminada: {copied}/{len(results)} copiadas")
        self.selection_ctrl.clear()
        self.ops_cache = []
        self.btn_safe.setEnabled(True)
        self.btn_prepare.setEnabled(True)
        self.refresh()

    def _copy_failed(self, message: str) -> None:
        self.is_executing = False
        self.btn_safe.setEnabled(True)
        self.btn_prepare.setEnabled(True)
        self.btn_execute.setEnabled(False)
        self.statusBar().showMessage(f"Error de ejecución: {message}")

    def _rename_profile(self) -> None:
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
        self.refresh()

    def _change_work_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Seleccionar directorio de trabajo", self.profile.work_dir
        )
        if not directory:
            return
        self.profile.work_dir = os.path.abspath(directory)
        try:
            save_profile(self.profile)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo guardar el directorio", str(exc))
            return
        self.refresh()

    def closeEvent(self, event) -> None:
        for page in self._source_pages.values():
            page.git_bar.deactivate()
            page.git_bar.controller.shutdown()
        super().closeEvent(event)

    def _delete_profile(self) -> None:
        answer = QMessageBox.question(
            self,
            "Eliminar perfil",
            "¿Eliminar el perfil y su configuración? No se borrarán los archivos "
            "del directorio de trabajo ni de las fuentes.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_profile(self.profile.id)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo eliminar el perfil", str(exc))
            return
        self.close()



