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

    def set_criteria(self, axis_a=None, axis_b=None, incidences=False, search="", owner="") -> None:
        self.axis_a = axis_a or None
        self.axis_b = axis_b or None
        self.only_incidences = bool(incidences)
        self.search = search or ""
        self.owner = owner or ""
        self.apply()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        src = self.sourceModel()
        if hasattr(src, "row"):
            row = src.row(source_row)
            if self.axis_a and row.axis_a != self.axis_a:
                return False
            if self.axis_b and row.axis_b != self.axis_b:
                return False
            if self.only_incidences and not row.incidences:
                return False
            if self.owner and row.owner != self.owner:
                return False
            if self.search and self.search.lower() not in row.path.lower():
                return False
            return True
        if not hasattr(src, "node_at"):
            return True
        idx = src.index(source_row, 0, source_parent)
        node = src.node_at(idx)
        if node.row is None:
            return True  # directorio estructural (posible vacío)
        row = node.row
        if self.axis_a and row.axis_a != self.axis_a:
            return False
        if self.axis_b and row.axis_b != self.axis_b:
            return False
        if self.only_incidences and not row.incidences:
            return False
        if self.owner and row.owner != self.owner:
            return False
        if self.search:
            needle = self.search.lower()
            if needle not in row.path.lower() and needle not in os.path.basename(row.path).lower():
                return False
        return True
