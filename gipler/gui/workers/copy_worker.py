"""Worker de copia (Fase 5: uso; Fase 1: estructura).

Ejecuta copy_engine.execute_operations en segundo plano tras la
autorización explícita del diálogo. Nunca se invoca desde Fases 1-4.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot
from gipler.copy_engine import execute_operations


class CopyWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, ops: list, authorized: bool, parent=None):
        super().__init__(parent)
        self.ops = ops
        self.authorized = authorized
        self.started = False

    @Slot()
    def run(self) -> None:
        self.started = True
        try:
            self.finished.emit(execute_operations(self.ops, authorized=self.authorized))
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))
