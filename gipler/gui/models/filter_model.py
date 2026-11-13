"""Modelo proxy de filtros (Fase 2 espec GUI §4).

Filtros combinables sobre el árbol: eje A, eje B, incidencias, búsqueda
por nombre/ruta y filtro por propietario. Los directorios estructurales
siempre pasan (permite directorios vacíos); los archivos se filtran.
El proxy no modifica los datos del motor.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt


def visible_file_count(proxy) -> int:
    """Nº de archivos visibles (recorre el árbol proxy)."""
    src = proxy.sourceModel()
    tree = getattr(src, "file_nodes", None)
    # Contar filas visibles del proxy: todas las filas cuyo nodo-fuente
    # tenga row no nula.
    count = 0
    def walk(parent_idx):
        nonlocal count
        for row in range(proxy.rowCount(parent_idx)):
            idx = proxy.index(row, 0, parent_idx)
            src_idx = proxy.mapToSource(idx)
            if hasattr(src, "node_at"):
                node = src.node_at(src_idx)
                if node is not None and node.row is not None:
                    count += 1
            else:
                count += 1  # fuente lista (Fase 1 antigua): cada fila es archivo
            walk(idx)
    walk(QModelIndex())
    return count


class FilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.axis_a: str | None = None
        self.axis_b: str | None = None
        self.only_incidences: bool = False
        self.search: str = ""
        self.owner: str = ""
        self.exclude_identical = False
        self.git_mode = False
        self.setSortRole(Qt.DisplayRole)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """Ordena directorios antes que archivos y cada grupo por nombre."""
        source = self.sourceModel()
        if not hasattr(source, "node_at"):
            return super().lessThan(left, right)
        left_node = source.node_at(left)
        right_node = source.node_at(right)
        if left_node.is_dir != right_node.is_dir:
            return left_node.is_dir
        left_name = (left_node.name.casefold(), left_node.name)
        right_name = (right_node.name.casefold(), right_node.name)
        return left_name < right_name

    def apply(self) -> None:
        self.invalidateFilter()

    def set_criteria(
        self,
        axis_a=None,
        axis_b=None,
        incidences=False,
        search="",
        owner="",
        exclude_identical=False,
    ) -> None:
        self.axis_a = axis_a or None
        self.axis_b = axis_b or None
        self.only_incidences = bool(incidences)
        self.search = search or ""
        self.owner = owner or ""
        self.exclude_identical = bool(exclude_identical)
        self.apply()

    def _row_matches(self, row) -> bool:
        if self.exclude_identical and row.axis_a == "identical":
            return False
        if self.axis_a and row.axis_a != self.axis_a:
            return False
        if self.axis_b:
            if self.git_mode:
                statuses = getattr(row, "git_statuses", frozenset())
                if self.axis_b == "unstaged_changes":
                    if not ({"modified_unstaged", "untracked"} & statuses):
                        return False
                elif self.axis_b not in statuses:
                    return False
            elif row.axis_b != self.axis_b:
                return False
        if self.only_incidences and not row.incidences:
            return False
        if self.owner and row.owner != self.owner:
            return False
        if self.search:
            needle = self.search.casefold()
            if needle not in row.path.casefold() and needle not in os.path.basename(row.path).casefold():
                return False
        return True

    def _has_matching_descendant(self, parent: QModelIndex) -> bool:
        source = self.sourceModel()
        for row_index in range(source.rowCount(parent)):
            index = source.index(row_index, 0, parent)
            node = source.node_at(index)
            if node.row is not None and self._row_matches(node.row):
                return True
            if node.is_dir and self._has_matching_descendant(index):
                return True
        return False

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        src = self.sourceModel()
        if hasattr(src, "row"):
            row = src.row(source_row)
            return self._row_matches(row)
        if not hasattr(src, "node_at"):
            return True
        idx = src.index(source_row, 0, source_parent)
        node = src.node_at(idx)
        if node.row is None:
            if self.git_mode:
                return self._has_matching_descendant(idx)
            if not self.exclude_identical:
                return True  # directorio estructural, como en la vista histórica
            return self._has_matching_descendant(idx)
        return self._row_matches(node.row)
