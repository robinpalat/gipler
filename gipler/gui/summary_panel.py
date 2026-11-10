"""Panel de resumen (pestaña Inicio).

Dos columnas: izquierda (lista interactiva de archivos relevantes
con colores semánticos, inspección y casillas de SelectionController),
derecha (contadores verticales, archivo seleccionado técnico,
pie de acciones). Sin tabla de directorios ni segunda herramienta operativa.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QComboBox,
    QSizePolicy,
    QSplitter,
    QWidget,
)

from gipler.report import tooltip_text


class SummaryPanel(QFrame):
    open_requested = Signal(object)
    exclude_requested = Signal(object)
    explorer_requested = Signal(object)
    copy_selection_changed = Signal(object, bool)

    RELEVANT = ("new_in_dev", "modified_in_dev", "missing_in_dev", "not_comparable")
    RELEVANT_DESTINATIONS = ("principal", "addons")
    WARNING_STATES = ("tracked_modified",)
    REPOSITORY_SETTING = "inicio/repositorio"
    VIEW_SETTING = "inicio/vista"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.counters: dict[str, object] = {}
        self.file_info = QLabel("Sin archivo seleccionado")
        self.file_info.setWordWrap(True)
        self.file_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._open_menu)
        self.list.itemDoubleClicked.connect(self._on_item_double)
        self.list.currentItemChanged.connect(self._on_item_changed)
        self.list.itemChanged.connect(self._on_copy_check_changed)
        self.dev_root = ""
        self.repo_roots: dict[str, str] = {}
        self._rows: list = []
        self._ops_cache: list = []
        self._selected_copy_keys: set[tuple[str, str]] = set()
        self._eligible_copy_keys: set[tuple[str, str]] = set()
        self._scoped_rows: list = []
        self._syncing_checks = False

        self.btn_execute = None
        self.btn_prepare = None
        self.btn_safe = None

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.repository_selector = QComboBox()
        self.repository_selector.addItem("Principal", "principal")
        self.repository_selector.addItem("Add-ons", "addons")
        from gipler.config import get_settings

        settings = get_settings()
        saved_destination = settings.value(self.REPOSITORY_SETTING, "principal")
        selected_destination = self.repository_selector.findData(saved_destination)
        self.repository_selector.setCurrentIndex(max(selected_destination, 0))
        self.repository_selector.currentIndexChanged.connect(self._on_repository_changed)

        self.view_selector = QComboBox()
        self.view_selector.addItem("Archivos relevantes", "relevantes")
        self.view_selector.addItem("Advertencias", "advertencias")
        self.view_selector.addItem("Incidencias", "incidencias")
        self.view_selector.addItem("Mostrar todo", "todo")
        saved_view = settings.value(self.VIEW_SETTING, "relevantes")
        selected_view = self.view_selector.findData(saved_view)
        self.view_selector.setCurrentIndex(max(selected_view, 0))
        self.view_selector.currentIndexChanged.connect(self._on_view_changed)

        selectors = QWidget()
        selectors_layout = QHBoxLayout(selectors)
        selectors_layout.setContentsMargins(0, 0, 0, 0)
        repository_label = QLabel("Repositorio:")
        repository_label.setBuddy(self.repository_selector)
        repository_label.setAccessibleName("Etiqueta de repositorio")
        self.repository_selector.setAccessibleName("Repositorio de Inicio")
        selectors_layout.addWidget(repository_label)
        selectors_layout.addWidget(self.repository_selector, 1)

        view_label = QLabel("Vista:")
        view_label.setBuddy(self.view_selector)
        view_label.setAccessibleName("Etiqueta de tipo de vista")
        self.view_selector.setAccessibleName("Tipo de vista de Inicio")
        selectors_layout.addWidget(view_label)
        selectors_layout.addWidget(self.view_selector, 1)

        self.repository_selector.setAccessibleName("Repositorio de Inicio")
        self.repository_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.view_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selectors_layout.setStretch(1, 1)
        selectors_layout.setStretch(3, 1)
        left_layout.addWidget(selectors)
        left_layout.addWidget(self.list)
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Estado de comparación"))
        self.counters_box = QWidget()
        cb = QVBoxLayout(self.counters_box)
        for key, label in (
            ("nuevos", "Nuevos en Dev"),
            ("modificados", "Modificados en Dev"),
            ("identicos", "Idénticos"),
            ("ausentes", "Ausentes en Dev"),
            ("advertencias", "Con advertencias/incidencias"),
            ("bloqueados", "Bloqueados (preparados)"),
        ):
            lab = QLabel(f"{label}: 0")
            self.counters[key] = (label, lab)
            cb.addWidget(lab)
        right_layout.addWidget(self.counters_box)
        right_layout.addWidget(QLabel("Archivo seleccionado (información técnica)"))
        right_layout.addWidget(self.file_info)
        self.foot = QWidget()
        foot_layout = QHBoxLayout(self.foot)
        from PySide6.QtWidgets import QPushButton

        self.btn_safe = QPushButton("Selección segura")
        self.btn_prepare = QPushButton("Preparar operaciones")
        self.btn_execute = QPushButton("Ejecutar copia (0)")
        self.btn_execute.setEnabled(False)
        foot_layout.addWidget(self.btn_safe)
        foot_layout.addWidget(self.btn_prepare)
        foot_layout.addWidget(self.btn_execute)
        right_layout.addStretch(1)
        right_layout.addWidget(self.foot)
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 63)
        split.setStretchFactor(1, 37)
        outer = QVBoxLayout(self)
        outer.addWidget(split)

    # API ---------------------------------------------------------
    def set_selected(self, row, dev_m: dict, repo_m: dict) -> None:
        if row is None:
            self.file_info.setText("Sin archivo seleccionado")
            return
        dev_path = os.path.join(self.dev_root, row.path) if self.dev_root else ""
        repo_root = self.repo_roots.get(row.destination, "")
        repo_path = os.path.join(repo_root, row.path) if repo_root else ""
        from gipler.report import markers, state_detail

        mark = markers(row)
        detail = state_detail(row)
        lines = [
            f"Ruta relativa: {row.path}" + (f"  [{mark}]" if mark else ""),
            f"Estado A: {row.axis_a}  |  Estado B: {row.axis_b}",
        ]
        if detail:
            lines.append(f"Detalle: {detail}")
        lines += [
            f"Existencia física — Dev: {dev_m.get('existe', 'no disponible')}  |  "
            f"Repositorio: {repo_m.get('existe', 'no disponible')}",
            f"Dev: {dev_path or '(sin ubicación)'}",
            "[Dev]",
            self._format_metadata(dev_m),
            f"Repositorio ({row.destination}): {repo_path or '(sin destino)'}",
            "[Repositorio]",
            self._format_metadata(repo_m),
        ]
        self.file_info.setText("\n".join(lines))

    @staticmethod
    def _format_metadata(metadata: dict) -> str:
        return ", ".join(f"{key}={value}" for key, value in metadata.items()) or "sin datos"

    @staticmethod
    def _row_for_item(item: QListWidgetItem | None):
        return item.data(Qt.UserRole) if item is not None else None

    def _on_item_changed(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        row = self._row_for_item(item)
        if row is None:
            return
        self.inspect_row(row)

    def _on_copy_check_changed(self, item: QListWidgetItem) -> None:
        if self._syncing_checks:
            return
        row = self._row_for_item(item)
        if row is None:
            return
        key = (row.destination, row.path)
        if key not in self._eligible_copy_keys:
            self.sync_operational_state(
                self._selected_copy_keys, self._eligible_copy_keys, self._ops_cache
            )
            return
        checked = item.checkState() == Qt.Checked
        if checked == (key in self._selected_copy_keys):
            return
        if checked:
            self._selected_copy_keys.add(key)
        else:
            self._selected_copy_keys.discard(key)
        self.copy_selection_changed.emit(row, checked)

    def sync_operational_state(
        self,
        selected_keys: set[tuple[str, str]],
        eligible_keys: set[tuple[str, str]],
        ops_cache: list,
    ) -> None:
        self._selected_copy_keys = set(selected_keys)
        self._eligible_copy_keys = set(eligible_keys)
        self._ops_cache = list(ops_cache or [])
        self._syncing_checks = True
        blocker = QSignalBlocker(self.list)
        for index in range(self.list.count()):
            item = self.list.item(index)
            row = self._row_for_item(item)
            if row is None:
                continue
            key = (row.destination, row.path)
            flags = item.flags()
            if key in self._eligible_copy_keys:
                item.setFlags(flags | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if key in self._selected_copy_keys else Qt.Unchecked
                )
            else:
                item.setCheckState(Qt.Unchecked)
                item.setFlags(flags & ~Qt.ItemIsUserCheckable)
        del blocker
        self._syncing_checks = False
        blocked_keys = {
            (op.destination, op.path)
            for op in self._ops_cache
            if getattr(op, "status", None) == "bloqueada"
        }
        label, counter = self.counters["bloqueados"]
        scoped_keys = {(row.destination, row.path) for row in self._scoped_rows}
        counter.setText(f"{label}: {len(blocked_keys & scoped_keys)}")
        self._update_execute_label(self._ops_cache)

    def inspect_row(self, row) -> None:
        """Inspección (no selección de copia): actualiza el panel técnico."""
        from gipler.gui.inspector import Inspector

        dev_path = os.path.join(self.dev_root, row.path) if self.dev_root else ""
        repo_root = self.repo_roots.get(row.destination, "")
        repo_path = os.path.join(repo_root, row.path) if repo_root else ""
        dev_meta = Inspector._meta(dev_path) if dev_path else {"existe": "sin ubicación"}
        repo_meta = Inspector._meta(repo_path) if repo_path else {"existe": "sin destino"}
        self.set_selected(row, dev_meta, repo_meta)

    def update_from(
        self,
        rows: list,
        ops_cache: list | None = None,
        selected_keys: set[tuple[str, str]] | None = None,
        eligible_keys: set[tuple[str, str]] | None = None,
    ) -> None:
        selected_item = self.list.currentItem()
        selected_row = self._row_for_item(selected_item)
        selected_identity = (
            (selected_row.destination, selected_row.path) if selected_row is not None else None
        )
        self._rows = list(rows or [])
        self._ops_cache = list(ops_cache or [])
        if selected_keys is not None:
            self._selected_copy_keys = set(selected_keys)
        if eligible_keys is not None:
            self._eligible_copy_keys = set(eligible_keys)
        destination = self.repository_selector.currentData()
        from gipler.ignore import is_excluded, load_patterns

        patterns = load_patterns()
        scoped_rows = [
            row for row in self._rows
            if row.destination == destination
            and row.axis_b != "ignored"
            and "excluded" not in row.incidences
            and not is_excluded(row.path, patterns)
        ]
        self._scoped_rows = scoped_rows
        scoped_keys = {(row.destination, row.path) for row in scoped_rows}
        blocked_keys = {
            (operation.destination, operation.path)
            for operation in self._ops_cache
            if getattr(operation, "status", None) == "bloqueada"
            and (operation.destination, operation.path) in scoped_keys
        }
        counts = {
            "nuevos": sum(1 for r in scoped_rows if r.axis_a == "new_in_dev"),
            "modificados": sum(1 for r in scoped_rows if r.axis_a == "modified_in_dev"),
            "identicos": sum(1 for r in scoped_rows if r.axis_a == "identical"),
            "ausentes": sum(1 for r in scoped_rows if r.axis_a == "missing_in_dev"),
            "advertencias": sum(1 for r in scoped_rows if r.incidences),
            "bloqueados": len(blocked_keys),
        }
        for key, (label, lab) in self.counters.items():
            lab.setText(f"{label}: {counts[key]}")
        from gipler.gui.models.comparison_tree import color_for_row

        self._syncing_checks = True
        blocker = QSignalBlocker(self.list)
        self.list.clear()
        self.file_info.setText("Sin archivo seleccionado")
        view = self.view_selector.currentData()
        seen_keys: set[tuple[str, str]] = set()
        for r in scoped_rows:
            key = (r.destination, r.path)
            if key in seen_keys or not self._matches_view(r, view, blocked_keys, patterns):
                continue
            seen_keys.add(key)
            color = color_for_row(r)
            item = QListWidgetItem(r.path)
            item.setData(Qt.UserRole, r)
            key = (r.destination, r.path)
            flags = item.flags()
            if key in self._eligible_copy_keys:
                item.setFlags(flags | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if key in self._selected_copy_keys else Qt.Unchecked
                )
            else:
                item.setFlags(flags & ~Qt.ItemIsUserCheckable)
            item.setToolTip(tooltip_text(r))
            if color:
                item.setForeground(QColor(color))
            self.list.addItem(item)
            if key == selected_identity:
                self.list.setCurrentItem(item)
        del blocker
        self._syncing_checks = False
        if selected_identity is not None and self.list.currentItem() is not None:
            self.inspect_row(self._row_for_item(self.list.currentItem()))
        self._update_execute_label(self._ops_cache)

    @classmethod
    def _matches_view(
        cls,
        row,
        view: str,
        blocked_keys: set[tuple[str, str]] | None = None,
        exclusion_patterns: list[str] | None = None,
    ) -> bool:
        if view == "relevantes":
            return cls._is_relevant(row, blocked_keys, exclusion_patterns)
        if view == "advertencias":
            return row.axis_b in cls.WARNING_STATES
        if view == "incidencias":
            return bool(row.incidences)
        if view == "todo":
            return True
        return False

    @classmethod
    def _is_relevant(
        cls,
        row,
        blocked_keys: set[tuple[str, str]] | None = None,
        exclusion_patterns: list[str] | None = None,
    ) -> bool:
        """Incluir estados de revisión, incidencias, ambigüedad o bloqueos."""
        from gipler.ignore import is_excluded

        if (
            row.axis_b == "ignored"
            or "excluded" in row.incidences
            or is_excluded(row.path, exclusion_patterns or [])
        ):
            return False
        return (
            row.axis_a in cls.RELEVANT
            or bool(row.incidences)
            or not row.owner
            or row.owner == "sin determinar"
            or (row.destination, row.path) in (blocked_keys or set())
        )

    def _on_repository_changed(self, _index: int) -> None:
        destination = self.repository_selector.currentData()
        if destination not in self.RELEVANT_DESTINATIONS:
            return
        from gipler.config import get_settings

        settings = get_settings()
        settings.setValue(self.REPOSITORY_SETTING, destination)
        settings.sync()
        self.update_from(self._rows, self._ops_cache)

    def _on_view_changed(self, _index: int) -> None:
        view = self.view_selector.currentData()
        from gipler.config import get_settings

        settings = get_settings()
        settings.setValue(self.VIEW_SETTING, view)
        settings.sync()
        self.update_from(self._rows, self._ops_cache)

    def set_location_roots(self, dev_root: str, repo_roots: dict[str, str]) -> None:
        self.dev_root = dev_root
        self.repo_roots = dict(repo_roots)

    def _open_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        menu = self.context_menu_for(item)
        if menu is None:
            return
        self.list.setCurrentItem(item)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def context_menu_for(self, item: QListWidgetItem | None) -> QMenu | None:
        row = self._row_for_item(item)
        if row is None:
            return None
        menu = QMenu(self)
        select_action = menu.addAction("Seleccionar")
        select_action.triggered.connect(lambda: self.list.setCurrentItem(item))
        open_action = menu.addAction("Abrir en explorador")
        open_action.triggered.connect(lambda: self.explorer_requested.emit(row))
        exclude_action = menu.addAction("Excluir")
        exclude_action.triggered.connect(lambda: self.exclude_requested.emit(row))
        return menu

    def _update_execute_label(self, ops_cache: list) -> None:
        if self.btn_execute is not None:
            n_exec = sum(1 for o in (ops_cache or []) if getattr(o, "status", None) == "copiable")
            self.btn_execute.setText(f"Ejecutar copia ({n_exec})")
            self.btn_execute.setEnabled(
                n_exec > 0 and not getattr(self.window(), "is_executing", False)
            )

    def _on_item_double(self, item: QListWidgetItem) -> None:
        row = self._row_for_item(item)
        if row is not None:
            self.open_requested.emit(row)