"""Panel de resumen (pestaña Inicio).

Dos columnas: izquierda (lista interactiva de archivos relevantes
con colores semánticos, inspección y casillas de SelectionController),
derecha (contadores verticales, archivo seleccionado técnico,
pie de acciones). Sin tabla de directorios ni segunda herramienta operativa.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QComboBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gipler.report import tooltip_text
from gipler.selection import row_ref_for, selection_key_for


class MetricLabel(QLabel):
    """Valor numérico con etiqueta editorial en una sola QLabel."""

    def __init__(self, label: str, value: str = "0", color: str = ""):
        super().__init__(f"{label}: {value}")
        self._metric_label = label
        self._metric_value = str(value)
        self._metric_color = color
        self.setTextFormat(Qt.PlainText)

    def set_value(self, value) -> None:
        self._metric_value = str(value)
        super().setText(f"{self._metric_label}: {self._metric_value}")
        self.update()

    def set_color(self, color: str) -> None:
        self._metric_color = color or ""
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        caption = self._metric_label
        value = self._metric_value
        base_size = self.font().pointSize()
        if base_size <= 0:
            base_size = 10
        caption_font = QFont(self.font())
        caption_font.setPointSize(max(9, base_size - 1))
        caption_font.setWeight(QFont.Weight.Normal)
        value_font = QFont(self.font())
        value_font.setPointSize(base_size + 3)
        value_font.setWeight(QFont.Weight.DemiBold)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(caption_font)
        painter.drawText(self.rect(), int(Qt.AlignLeft | Qt.AlignVCenter), caption)
        if self._metric_color:
            painter.setPen(QColor(self._metric_color))
        painter.setFont(value_font)
        painter.drawText(
            self.rect(), int(Qt.AlignRight | Qt.AlignVCenter), value
        )
        painter.end()


class SummaryPanel(QFrame):
    open_requested = Signal(object)
    exclude_requested = Signal(object)
    explorer_requested = Signal(object)
    copy_selection_changed = Signal(object, bool)
    # (ruta relativa, id de referencia) — decisión de pertenencia, nunca copia.
    assign_requested = Signal(str, str)
    reference_changed = Signal(str)
    copy_requested = Signal(object)
    delete_requested = Signal(object)
    discard_requested = Signal(object)

    RELEVANT = ("new_in_dev", "modified_in_dev", "missing_in_dev", "not_comparable")
    WARNING_STATES = ("tracked_modified",)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.counters: dict[str, object] = {}
        self.file_info = QLabel("Sin archivo seleccionado")
        self.file_info.setWordWrap(True)
        self.file_info.setAlignment(Qt.AlignLeft | Qt.AlignTop)
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
        left_layout.setContentsMargins(12, 0, 12, 12)
        left_layout.setSpacing(10)

        self.repository_selector = QComboBox()
        self.repository_selector.currentIndexChanged.connect(self._on_repository_changed)

        self.view_selector = QComboBox()
        self.view_selector.addItem("Archivos relevantes", "relevantes")
        self.view_selector.addItem("Advertencias", "advertencias")
        self.view_selector.addItem("Incidencias", "incidencias")
        self.view_selector.addItem("Mostrar todo", "todo")
        self.view_selector.setCurrentIndex(0)
        self.view_selector.currentIndexChanged.connect(self._on_view_changed)

        self.repository_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.view_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        context = QFrame()
        context.setObjectName("inicioContext")
        context.setFrameShape(QFrame.Shape.NoFrame)
        context.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        context_layout = QHBoxLayout(context)
        context_layout.setContentsMargins(10, 8, 10, 8)
        context_layout.setSpacing(12)
        repository_label = QLabel("Directorio de referencia")
        repository_label.setBuddy(self.repository_selector)
        repository_label.setAccessibleName("Etiqueta de repositorio")
        repository_label.setObjectName("contextLabel")
        self.repository_selector.setAccessibleName("Directorio de referencia de Inicio")
        context_layout.addWidget(repository_label)
        context_layout.addWidget(self.repository_selector, 1)
        view_label = QLabel("Vista")
        view_label.setBuddy(self.view_selector)
        view_label.setAccessibleName("Etiqueta de tipo de vista")
        view_label.setObjectName("contextLabel")
        self.view_selector.setAccessibleName("Tipo de vista de Inicio")
        context_layout.addWidget(view_label)
        context_layout.addWidget(self.view_selector, 1)
        self.selectors = context
        left_layout.addWidget(context)

        self.empty_state = QLabel(
            "El directorio de trabajo está vacío."
        )
        self.empty_state.setObjectName("profileEmptyState")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.empty_state.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.empty_state.setVisible(False)
        left_layout.addWidget(self.empty_state)

        self._visual_theme = ""
        self._visual_theme_pending = ""
        self._assignment_targets = []
        self._destination_names: dict[str, str] = {}
        self._assign_buttons = {}
        self._assign_combos = {}
        self.assign_box = QFrame()
        self.assign_box.setObjectName("pendingAssignments")
        self.assign_box.setFrameShape(QFrame.Shape.NoFrame)
        self.assign_box.setMaximumHeight(260)
        assign_layout = QVBoxLayout(self.assign_box)
        assign_layout.setContentsMargins(12, 10, 12, 10)
        assign_layout.setSpacing(6)
        self.assign_title = QLabel("Archivos nuevos pendientes de asignación")
        self.assign_title.setObjectName("sectionTitle")
        assign_layout.addWidget(self.assign_title)
        self.assign_rows = QWidget()
        self.assign_rows_layout = QVBoxLayout(self.assign_rows)
        self.assign_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.assign_rows_layout.setSpacing(4)
        self.assign_rows_scroll = QScrollArea()
        self.assign_rows_scroll.setWidgetResizable(True)
        self.assign_rows_scroll.setWidget(self.assign_rows)
        self.assign_rows_scroll.setMaximumHeight(180)
        self.assign_rows_scroll.setMinimumHeight(0)
        self.assign_rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        assign_layout.addWidget(self.assign_rows_scroll)
        self.assign_box.setVisible(False)
        self.assign_separator = QWidget()
        self.assign_separator.setFixedHeight(1)
        self.assign_separator.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        self.assign_separator.setBackgroundRole(QPalette.ColorRole.Mid)
        self.assign_separator.setAutoFillBackground(True)
        self.assign_separator.setVisible(False)
        left_layout.addWidget(self.assign_box)
        left_layout.addWidget(self.assign_separator)
        left_layout.addWidget(self.list, 1)
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 6, 14, 14)
        right_layout.setSpacing(12)

        status_section = QFrame()
        status_section.setObjectName("statusSection")
        status_section.setFrameShape(QFrame.Shape.NoFrame)
        status_section.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        status_layout = QVBoxLayout(status_section)
        status_layout.setContentsMargins(14, 4, 14, 12)
        status_layout.setSpacing(8)
        status_title = QLabel("Estado de comparación")
        status_title.setObjectName("sectionTitle")
        status_layout.addWidget(status_title)
        status_layout.addWidget(self._section_separator())
        self.counters_box = QWidget()
        metrics_layout = QHBoxLayout(self.counters_box)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(12)
        left_metrics = QWidget()
        left_metrics_layout = QVBoxLayout(left_metrics)
        left_metrics_layout.setContentsMargins(0, 0, 0, 0)
        left_metrics_layout.setSpacing(6)
        right_metrics = QWidget()
        right_metrics_layout = QVBoxLayout(right_metrics)
        right_metrics_layout.setContentsMargins(0, 0, 0, 0)
        right_metrics_layout.setSpacing(6)
        metrics_separator = QWidget()
        metrics_separator.setFixedWidth(1)
        metrics_separator.setMinimumHeight(40)
        metrics_separator.setBackgroundRole(QPalette.ColorRole.Mid)
        metrics_separator.setAutoFillBackground(True)
        metrics_layout.addWidget(left_metrics, 1)
        metrics_layout.addWidget(metrics_separator)
        metrics_layout.addWidget(right_metrics, 1)
        metric_colors = {
            "nuevos": "new_in_dev",
            "modificados": "modified_in_dev",
            "identicos": "identical",
            "ausentes": "missing_in_dev",
            "advertencias": "ambiguous",
            "bloqueados": "identical",
        }
        for index, (key, label) in enumerate(
            (
                ("nuevos", "Nuevos en Dev"),
                ("identicos", "Idénticos"),
                ("advertencias", "Con advertencias/incidencias"),
                ("modificados", "Modificados en Dev"),
                ("ausentes", "Ausentes en Dev"),
                ("bloqueados", "Bloqueados (preparados)"),
            )
        ):
            color = self._semantic_color(metric_colors[key])
            metric = MetricLabel(label, "0", color)
            self.counters[key] = (label, metric)
            if index < 3:
                left_metrics_layout.addWidget(metric)
            else:
                right_metrics_layout.addWidget(metric)
        status_layout.addWidget(self.counters_box)
        right_layout.addWidget(status_section)

        file_section = QFrame()
        file_section.setObjectName("fileSection")
        file_section.setFrameShape(QFrame.Shape.NoFrame)
        file_section.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        file_layout = QVBoxLayout(file_section)
        file_layout.setContentsMargins(14, 12, 14, 12)
        file_layout.setSpacing(8)
        file_title = QLabel("Archivo seleccionado")
        file_title.setObjectName("sectionTitle")
        file_layout.addWidget(file_title)
        file_layout.addWidget(self._section_separator())
        self.file_info_scroll = QScrollArea()
        self.file_info_scroll.setWidgetResizable(True)
        self.file_info_scroll.setWidget(self.file_info)
        self.file_info_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.file_info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_info_scroll.setMaximumHeight(560)
        self.file_info_scroll.setMinimumHeight(60)
        self.file_info_scroll.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        file_layout.addWidget(self.file_info_scroll)
        file_section.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        right_layout.addWidget(file_section, 1)

        self.foot = QWidget()
        foot_layout = QHBoxLayout(self.foot)
        foot_layout.setContentsMargins(0, 0, 0, 0)
        foot_layout.setSpacing(8)
        self.btn_safe = QPushButton("Selección segura")
        self.btn_prepare = QPushButton("Preparar operaciones")
        self.btn_execute = QPushButton("Ejecutar copia (0)")
        self.btn_execute.setEnabled(False)
        foot_layout.addWidget(self.btn_safe)
        foot_layout.addWidget(self.btn_prepare)
        foot_layout.addWidget(self.btn_execute)
        right_layout.addWidget(self.foot)
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 68)
        split.setStretchFactor(1, 32)
        split.setHandleWidth(1)
        outer = QVBoxLayout(self)
        outer.addWidget(split)
        self._apply_visual_style()

    @staticmethod
    def _section_separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("sectionSeparator")
        separator.setFrameShape(QFrame.Shape.NoFrame)
        separator.setFixedHeight(1)
        separator.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return separator

    def _semantic_color(self, key: str) -> str:
        from gipler.gui import theme

        return theme.semantic(theme.load_preference(), key)

    def _apply_visual_style(self) -> None:
        from gipler.gui import theme

        palette = theme.PALETTES.get(
            theme.load_preference(), theme.PALETTES["oscuro"]
        )
        self.setStyleSheet(
            f"""
QFrame#inicioContext {{ background: {palette['panel2']}; border: 1px solid {palette['borde']}; border-radius: 10px; }}
QFrame#pendingAssignments {{ background: transparent; border: none; border-radius: 0px; }}
QFrame#statusSection, QFrame#fileSection {{ background: transparent; border: none; }}
QFrame#sectionSeparator {{ background: {palette['borde']}; border: none; }}
QLabel#sectionTitle {{ color: {palette['texto']}; font-size: 13px; font-weight: 700; }}
QLabel#contextLabel {{ color: {palette['texto2']}; font-size: 11px; padding: 4px 8px; }}
"""
        )
        self.list.setStyleSheet(
            f"""
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 5px 8px; background: transparent; }}
QListWidget::item:selected {{ background: {palette['seleccion']}; }}
QListWidget::item:hover {{ background: {palette['panel2']}; }}
QSplitter::handle {{ background: {palette['borde']}; }}
"""
        )
        combo_style = f"""
QComboBox {{ background: {palette['tabla']}; color: {palette['texto']}; border: 1px solid {palette['borde']}; border-radius: 6px; padding: 6px 8px; }}
QComboBox:hover {{ border-color: {palette['acento']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
"""
        self.repository_selector.setStyleSheet(combo_style)
        self.view_selector.setStyleSheet(combo_style)
        self.file_info.setStyleSheet(
            f"QLabel {{ background: transparent; color: {palette['texto']}; }}"
        )
        self.btn_safe.setStyleSheet(
            f"""
QPushButton {{ background: transparent; color: {palette['acento']}; border: 1px solid {palette['borde']}; border-radius: 6px; padding: 7px 12px; }}
QPushButton:hover {{ border-color: {palette['acento']}; }}
QPushButton:disabled {{ color: {palette['texto2']}; border-color: {palette['borde']}; }}
"""
        )
        self.btn_prepare.setStyleSheet(
            f"""
QPushButton {{ background: {palette['panel2']}; color: {palette['texto']}; border: 1px solid {palette['borde']}; border-radius: 6px; padding: 7px 12px; }}
QPushButton:hover {{ border-color: {palette['acento']}; }}
QPushButton:disabled {{ color: {palette['texto2']}; }}
"""
        )
        self.btn_execute.setStyleSheet(
            f"""
QPushButton {{ background: {palette['acento']}; color: #FFFFFF; border: 1px solid {palette['acento']}; border-radius: 6px; padding: 7px 12px; }}
QPushButton:disabled {{ background: {palette['panel2']}; color: {palette['texto2']}; border-color: {palette['borde']}; }}
"""
        )
        metric_colors = {
            "nuevos": "new_in_dev",
            "modificados": "modified_in_dev",
            "identicos": "identical",
            "ausentes": "missing_in_dev",
            "advertencias": "ambiguous",
            "bloqueados": "identical",
        }
        for key, (_label, metric) in self.counters.items():
            metric.set_color(self._semantic_color(metric_colors[key]))
        from gipler.gui.theme import load_preference

        self._visual_theme = load_preference()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            if getattr(self, "_updating_visual_style", False):
                return
            from gipler.gui.theme import load_preference

            current = load_preference()
            if current == self._visual_theme:
                return
            if not self.isVisible():
                # Evita reestilizar widgets ya cerrados/ocultos de ventanas
                # anteriores; se aplicará al volver a mostrarse.
                self._visual_theme_pending = current
                return
            self._visual_theme = current
            self._updating_visual_style = True
            try:
                self._apply_visual_style()
            finally:
                self._updating_visual_style = False

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        pending = self._visual_theme_pending
        if pending and pending != self._visual_theme:
            self._visual_theme_pending = ""
            self._updating_visual_style = True
            try:
                self._apply_visual_style()
            finally:
                self._updating_visual_style = False

    # API ---------------------------------------------------------
    def _set_assign_box_visible(self, visible: bool) -> None:
        self.assign_box.setVisible(visible)
        self.assign_separator.setVisible(visible)

    def set_empty_state(self, visible: bool) -> None:
        self.empty_state.setVisible(visible)
        self.selectors.setVisible(not visible)
        self.list.setVisible(not visible)
        if visible:
            self._set_assign_box_visible(False)

    def set_selected(self, row, dev_m: dict, repo_m: dict) -> None:
        self.file_info.setTextFormat(Qt.RichText)
        self.file_info_scroll.setMaximumHeight(60 if row is None else 560)
        if row is None:
            self.file_info.setText(
                "<span>Sin archivo seleccionado</span>"
            )
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
        blockers = getattr(row, "copy_blockers", ())
        if blockers:
            from gipler.copy_policy import describe_blockers

            lines.append("Copia: " + "; ".join(describe_blockers(blockers)))
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
        heading = (
            f"<div style='font-size: 15px; font-weight: 600; "
            f"margin-bottom: 6px;'>{row.path}</div>"
        )
        self.file_info.setText(heading + "<br>".join(lines))

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
        key = selection_key_for(row)
        if key is None or key not in self._eligible_copy_keys:
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
            key = selection_key_for(row)
            flags = item.flags()
            if key is not None and key in self._eligible_copy_keys:
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
        _label, counter = self.counters["bloqueados"]
        scoped_keys = {
            key
            for row in self._scoped_rows
            if (key := selection_key_for(row)) is not None
        }
        counter.set_value(len(blocked_keys & scoped_keys))
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
        selected_identity = row_ref_for(selected_row)
        self._rows = list(rows or [])
        self._ops_cache = list(ops_cache or [])
        if selected_keys is not None:
            self._selected_copy_keys = set(selected_keys)
        if eligible_keys is not None:
            self._eligible_copy_keys = set(eligible_keys)
        destination = self.repository_selector.currentData()
        patterns: list[str] = []
        scoped_rows = [
            row for row in self._rows
            if row.destination == destination
            and row.axis_b != "ignored"
            and "excluded" not in row.incidences
        ]
        self._scoped_rows = scoped_rows
        scoped_keys = {
            key
            for row in scoped_rows
            if (key := selection_key_for(row)) is not None
        }
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
            "advertencias": sum(
                1 for r in scoped_rows
                if r.incidences or getattr(r, "copy_blockers", ())
            ),
            "bloqueados": len(blocked_keys),
        }
        for key, (_label, lab) in self.counters.items():
            lab.set_value(counts[key])
        from gipler.gui.models.comparison_tree import color_for_row

        self._syncing_checks = True
        blocker = QSignalBlocker(self.list)
        self.list.clear()
        self.file_info.setText("Sin archivo seleccionado")
        view = self.view_selector.currentData()
        seen_refs: set[tuple[str, str]] = set()
        for r in scoped_rows:
            row_ref = row_ref_for(r)
            if row_ref is None or row_ref in seen_refs:
                continue
            if not self._matches_view(r, view, blocked_keys, patterns):
                continue
            seen_refs.add(row_ref)
            key = selection_key_for(r)
            color = color_for_row(r)
            item = QListWidgetItem(r.path)
            item.setData(Qt.UserRole, r)
            flags = item.flags()
            if key is not None and key in self._eligible_copy_keys:
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
            if row_ref == selected_identity:
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
            return bool(row.incidences or getattr(row, "copy_blockers", ()))
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
        key = selection_key_for(row)
        return (
            row.axis_a in cls.RELEVANT
            or bool(row.incidences)
            or bool(getattr(row, "copy_blockers", ()))
            or not row.owner
            or row.owner == "sin determinar"
            or (key is not None and key in (blocked_keys or set()))
        )

    def _on_repository_changed(self, _index: int) -> None:
        self.update_from(self._rows, self._ops_cache)
        reference_id = self.repository_selector.currentData()
        if reference_id:
            self.reference_changed.emit(str(reference_id))

    def _on_view_changed(self, _index: int) -> None:
        self.update_from(self._rows, self._ops_cache)

    def set_location_roots(self, dev_root: str, repo_roots: dict[str, str]) -> None:
        self.dev_root = dev_root
        self.repo_roots = dict(repo_roots)

    # -- archivos nuevos pendientes de asignación ----------------------
    def set_assignment_targets(self, targets) -> None:
        """Referencias activas del perfil, siempre obtenidas dinámicamente."""
        self._assignment_targets = [
            (str(source_id), str(name)) for source_id, name in targets
        ]

    def set_pending_assignments(self, entries) -> None:
        self._assign_buttons.clear()
        self._assign_combos.clear()
        while self.assign_rows_layout.count():
            item = self.assign_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        entries = list(entries or ())
        self.assign_title.setText(
            f"Archivos nuevos pendientes de asignación ({len(entries)})"
        )
        if not entries:
            self._set_assign_box_visible(False)
            return
        from gipler.gui.theme import load_preference, semantic

        color = semantic(load_preference(), "new_in_dev")
        for entry in entries:
            path = entry.path
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)
            button = QPushButton("+")
            button.setFixedSize(22, 22)
            button.setFlat(True)
            button.setToolTip("Asignar a")
            button.setAccessibleName(f"Asignar {path} a una referencia")
            button.setObjectName("assignPlusButton")
            button.clicked.connect(
                lambda _checked=False, p=path, b=button: self._open_assign_menu(
                    p, b
                )
            )
            name = QLabel(path)
            name.setStyleSheet(f"color: {color};")
            name.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(button)
            row_layout.addWidget(name, 1)
            self.assign_rows_layout.addWidget(row)
            self._assign_buttons[path] = button
        self._set_assign_box_visible(True)

    def build_assign_menu(self, path: str) -> QMenu:
        menu = QMenu(self)
        header = menu.addAction("Asignar a")
        header.setEnabled(False)
        menu.addSeparator()
        if not self._assignment_targets:
            empty = menu.addAction("Sin referencias activas")
            empty.setEnabled(False)
        else:
            for source_id, source_name in self._assignment_targets:
                action = menu.addAction(source_name)
                action.setData(source_id)
                action.triggered.connect(
                    lambda _checked=False, p=path, s=source_id: self.assign_path(
                        p, s
                    )
                )
        return menu

    def _open_assign_menu(self, path: str, button: QPushButton) -> None:
        menu = self.build_assign_menu(path)
        menu.exec(button.mapToGlobal(QPoint(0, button.height())))

    def assign_path(self, path: str, source_id: str) -> None:
        if not source_id:
            return
        self.assign_requested.emit(path, str(source_id))

    def pending_paths(self) -> list[str]:
        return list(self._assign_buttons)

    def _assignment_selected(self, path: str, combo: QComboBox) -> None:
        source_id = combo.currentData() or ""
        if not source_id:
            return
        blocker = QSignalBlocker(combo)
        combo.setCurrentIndex(0)
        del blocker
        self.assign_requested.emit(path, str(source_id))

    def set_destinations(
        self, destinations: list[tuple[str, str]], selected: str | None = None
    ) -> None:
        self._destination_names = {
            str(destination_id): str(label)
            for destination_id, label in destinations
        }
        self.repository_selector.blockSignals(True)
        self.repository_selector.clear()
        for destination_id, label in destinations:
            self.repository_selector.addItem(label, destination_id)
        index = self.repository_selector.findData(selected)
        if index < 0 and self.repository_selector.count():
            index = 0
        self.repository_selector.setCurrentIndex(index)
        self.repository_selector.blockSignals(False)
        self.update_from(self._rows, self._ops_cache)

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
        copy_action = menu.addAction(
            f"Copiar a {self._destination_name(row.destination)}"
        )
        copy_action.setEnabled(selection_key_for(row) is not None)
        copy_action.triggered.connect(lambda: self.copy_requested.emit(row))
        select_action = menu.addAction("Seleccionar")
        select_action.triggered.connect(lambda: self.list.setCurrentItem(item))
        open_action = menu.addAction("Abrir en explorador")
        open_action.triggered.connect(lambda: self.explorer_requested.emit(row))
        exclude_action = menu.addAction("Excluir")
        exclude_action.triggered.connect(lambda: self.exclude_requested.emit(row))
        menu.addSeparator()
        if self._discard_candidate(row):
            discard_action = menu.addAction("Descartar cambios de Git…")
            discard_action.triggered.connect(
                lambda: self.discard_requested.emit(row)
            )
        delete_action = menu.addAction("Eliminar…")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(row))
        return menu

    def _destination_name(self, destination_id: str) -> str:
        root = self.repo_roots.get(destination_id, "")
        if root:
            name = os.path.basename(os.path.normpath(root))
            if name:
                return name
        return self._destination_names.get(destination_id, destination_id)

    @staticmethod
    def _discard_candidate(row) -> bool:
        statuses = set(getattr(row, "git_statuses", ()) or ())
        return bool(
            row.axis_b == "tracked_modified"
            or getattr(row, "git_change", "")
            or getattr(row, "git_stage", "")
            or statuses & {"modified_unstaged", "staged"}
        )

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