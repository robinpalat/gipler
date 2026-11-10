"""Árbol de comparación (Fase 2 GUI §3).

Un solo árbol lógico compartido por ambos exploradores. Cada fila de
analysis.analyze() aporta una ruta relativa. Los directorios son
estructurales e independientes de los filtros (permiten directorios
vacíos visibles). Cada archivo conserva eje A y eje B independientes,
propietario, destino e incidencias; la ausencia en Dev o en el
repositorio se representa por el eje A, sin fusionar ejes.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor


class Node:
    __slots__ = ("name", "path", "children", "row", "is_dir", "parent", "pos")

    def __init__(self, name: str, path: str, row=None, is_dir: bool = False, parent: "Node | None" = None, pos: int = 0):
        self.name = name
        self.path = path
        self.children: dict[str, Node] = {}
        self.row = row
        self.is_dir = is_dir
        self.parent = parent
        self.pos = pos


# Codificación cromática semántica de los estados (Fase, espec GUI).
# Colores legibles en temas claros y oscuros; mid-interface foreground.
STATE_COLORS = {
    "new_in_dev": "#2e7d32",          # verde
    "modified_in_dev": "#1565c0",     # azul
    "identical": "#5f6368",           # gris neutro
    "missing_in_dev": "#9aa0a6",      # gris atenuado (más claro)
    "ambiguous": "#e8710a",           # naranja (ambiguo/sin determinar)
}
AMBIGUOUS_INCIDENCES = {
    "status_unrecognized",
    "status_development",
    "shared_file",
    "unknown_owner",
    "ambiguous",
}


def color_for_row(row, theme: str = "oscuro") -> str:
    """Prioridad visual: ambigüedad > estados eje A; tonos por tema."""
    if row is None:
        return ""
    from gipler.gui.theme import semantic
    sm = semantic(theme, "")
    if (
        not row.owner
        or row.owner == "sin determinar"
        or row.destination not in ("principal", "addons")
        or (AMBIGUOUS_INCIDENCES & set(row.incidences))
    ):
        return semantic(theme, "ambiguous")
    return semantic(theme, row.axis_a)


class ComparisonTreeModel(QAbstractItemModel):
    copy_selection_changed = Signal(object, bool)

    def __init__(self, rows: list | None = None, destination: str = "principal", parent=None):
        super().__init__(parent)
        self.destination = destination
        self.checked_keys: set[tuple[str, str]] = set()
        self.eligible_keys: set[tuple[str, str]] | None = None
        self.semantic_theme = "oscuro"
        self._root = Node("", "")
        self._rows: list = []
        if rows is not None:
            self.set_rows(rows, destination)

    # -- construcción -------------------------------------------------
    def set_rows(self, rows: list, destination: str) -> None:
        self.beginResetModel()
        self.destination = destination
        self._rows = [r for r in rows if r.destination == destination]
        self._build()
        self.endResetModel()

    def _build(self) -> None:
        self._root = Node("", "")
        for r in self._rows:
            parts = [p for p in r.path.split("/") if p]
            node = self._root
            cur = ""
            for i, part in enumerate(parts):
                cur = "/".join(parts[: i + 1])
                last = i == len(parts) - 1
                if part not in node.children:
                    node.children[part] = Node(
                        part, cur,
                        row=(r if last else None),
                        is_dir=(not last),
                        parent=node, pos=len(node.children),
                    )
                node = node.children[part]

    def _node_for(self, index: QModelIndex) -> Node:
        if not index.isValid():
            return self._root
        return index.internalPointer()

    # -- QAbstractItemModel -------------------------------------------
    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        return bool(self._node_for(parent).children)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._node_for(parent).children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 3  # Nombre | Estado destino/Git | Advertencias

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        node = self._node_for(parent)
        if row < 0 or row >= len(node.children):
            return QModelIndex()
        child = list(node.children.values())[row]
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex) -> QModelIndex:
        node = self._node_for(index)
        if node.parent is None or node.parent is self._root:
            return QModelIndex()
        return self.createIndex(node.parent.pos, 0, node.parent)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        node = self._node_for(index)
        if role == Qt.UserRole + 1:
            return node.path
        if role == Qt.ToolTipRole:
            if node.row is not None:
                return (
                    f"{node.path}\n{node.row.owner} -> {node.row.destination} "
                    f"| A={node.row.axis_a} B={node.row.axis_b}"
                    + (f" †{','.join(node.row.incidences)}" if node.row.incidences else "")
                )
            return node.path
        if role == Qt.CheckStateRole:
            if index.column() == 0 and node.row is not None:
                return Qt.Checked if (node.row.destination, node.path) in self.checked_keys else Qt.Unchecked
            return None
        if role == Qt.ForegroundRole and index.column() == 0 and node.row is not None:
            color = color_for_row(node.row, self.semantic_theme)
            if color:
                return QColor(color)
            return None
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return node.name
            if node.row is not None and index.column() == 1:
                return node.row.axis_b
            if node.row is not None and index.column() == 2:
                return ",".join(node.row.incidences)
        return None

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["Nombre", "Estado", "Advertencias"][section]

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        node = self._node_for(index)
        if node.row is None:
            return False
        key = (node.row.destination, node.path)
        if self.eligible_keys is not None and key not in self.eligible_keys:
            return False
        # Qt pasa el valor como CheckState (enum) o int según la vía:
        # aceptar ambos (value.value == 2 o value == 2).
        new_val = getattr(value, "value", value)
        was_checked = key in self.checked_keys
        if new_val == 2:
            self.checked_keys.add(key)
        else:
            self.checked_keys.discard(key)
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        if was_checked != (new_val == 2):
            self.copy_selection_changed.emit(key, new_val == 2)
        return True

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        base |= Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0 and index.isValid():
            node = self._node_for(index)
            key = (node.row.destination, node.path) if node.row is not None else None
            if node.row is not None and (
                self.eligible_keys is None or key in self.eligible_keys
            ):
                base |= Qt.ItemIsUserCheckable
        return base

    def node_at(self, index: QModelIndex) -> Node:
        return self._node_for(index)

    def file_nodes(self) -> list[Node]:
        out: list[Node] = []
        stack = [self._root]
        while stack:
            n = stack.pop()
            if n.row is not None:
                out.append(n)
            stack.extend(n.children.values())
        return out
