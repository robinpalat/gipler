"""Worker de análisis (Fase 5: uso; Fase 1: estructura).

Ejecuta analysis.analyze() fuera del hilo gráfico y emite
( filas, meta, warnings ) al terminar. Solo lectura.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot
from gipler.analysis import analyze


class AnalysisWorker(QObject):
    finished = Signal(list, dict, list)
    failed = Signal(str)

    def __init__(self, dev: str, principal: str, addons: str, parent=None):
        super().__init__(parent)
        self.dev, self.principal, self.addons = dev, principal, addons

    @Slot()
    def run(self) -> None:
        try:
            _, rows, info = analyze(self.dev, self.principal, self.addons)
            self.finished.emit(rows, info["meta"], info["warnings"])
        except Exception as e:  # pragma: no cover - error visible en GUI
            self.failed.emit(str(e))
