"""Diálogo de revisión de operaciones (Fase 4).

Tabla de resultados reales de build_operations(). Botón Ejecutar
deshabilitado (Fase 5); Cancelar discards ops_cache conservando la
selección. Sin escrituras.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout


class OperationsDialog(QDialog):
    HEADER = ["Ruta", "Origen", "Destino", "Estado", "Advertencias"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Revisión de operaciones (preparación, sin ejecutar)")
        self.table = QTableWidget(0, len(self.HEADER))
        self.table.setHorizontalHeaderLabels(self.HEADER)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 220)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.reject)
        self.exec_btn = QPushButton("Ejecutar", self)
        self.exec_btn.setToolTip("Autoriza y ejecuta solo las operaciones copiables revisadas")
        self.exec_btn.setEnabled(False)  # Fase 5: se habilita tras preparar
        self.accepted_authorization = False
        self.exec_btn.clicked.connect(self._on_execute)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.exec_btn)
        layout.addWidget(self.buttons)

    def _on_execute(self) -> None:
        self.accepted_authorization = True
        self.accept()

    def set_operations(self, ops: list) -> None:
        self.table.setRowCount(len(ops))
        n_copiable = 0
        for r, o in enumerate(ops):
            warn = "; ".join(o.blockers) if o.blockers else ""
            if o.status == "copiable":
                n_copiable += 1
            for c, v in enumerate((o.path, o.src, o.dst, o.status, warn)):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.exec_btn.setEnabled(n_copiable > 0 and self.exec_btn is not None)
        self.exec_btn.setText(f"Ejecutar ({n_copiable} copiables)")

    def summary(self) -> str:
        counts = {"copiable": 0, "bloqueada": 0, "identica": 0}
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 3)
            if item and item.text() in counts:
                counts[item.text()] += 1
        return ", ".join(f"{k}={v}" for k, v in counts.items())
