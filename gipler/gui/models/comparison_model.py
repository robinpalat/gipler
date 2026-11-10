"""Modelo de filas del análisis ( Fase 1 spec GUI §3-§4).

QAbstractListModel sobre las Row de analysis.analyze(). Dos ejes
independientes preservados: axis_a (comparación) y axis_b (Git).
Propiedad, destino e incidencias como datos independientes.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ComparisonModel(QAbstractListModel):
    def __init__(self, rows: list | None = None, parent=None):
        super().__init__(parent)
        self._rows: list = list(rows or [])

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows) if not parent.isValid() else 0

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return r.path
        if role == Qt.ToolTipRole:
            return (
                f"{r.owner} -> {r.destination} | A={r.axis_a} B={r.axis_b}"
                + (f" †{','.join(r.incidences)}" if r.incidences else "")
            )
        return None

    def row(self, index: int):
        return self._rows[index]

    def all_rows(self) -> list:
        return list(self._rows)
