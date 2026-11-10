"""Inspector lateral derecho (Fase 3: contenido completo).

Tres pestañas: Resumen, Diferencias (visor de dos columnas), Información.
La metadatuología se lee del archivo seleccionado en el momento
(lstat + hash bajo demanda): no se recalculan inventarios del scanner.
"""
from __future__ import annotations

import hashlib
import os

from PySide6.QtWidgets import QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget

from gipler.gui.diff_view import DiffViewer
from gipler.report import Row


class Inspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabs = QTabWidget()
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.diff = DiffViewer()
        self.tabs.addTab(self.summary, "Resumen")
        self.tabs.addTab(self.diff, "Diferencias")
        self.tabs.addTab(self.info, "Información")
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

    # -- metadatos (bajo demanda, solo del archivo seleccionado) --------
    @staticmethod
    def _meta(path: str) -> dict:
        if not os.path.lexists(path):
            return {"existe": "no"}
        st = os.lstat(path)
        kind = "symlink" if os.path.islink(path) else ("dir" if os.path.isdir(path) else "file")
        m = {"existe": "sí", "tipo": kind, "tamaño": str(st.st_size),
             "permisos": oct(st.st_mode & 0o777),
             "ejecutable": str(bool(st.st_mode & 0o111))}
        if kind == "symlink":
            m["destino_enlace"] = os.readlink(path)
        elif kind == "file":
            h = hashlib.sha256()
            try:
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                m["sha256"] = h.hexdigest()
            except OSError:
                m["sha256"] = "(no legible)"
        return m

    @staticmethod
    def _fmt(meta: dict) -> str:
        return "\n".join(f"{k}: {v}" for k, v in meta.items())

    # -- API --------------------------------------------------------------
    def show_file(self, row: Row, dev_root: str, repo_root: str) -> None:
        """Actualiza las tres pestañas para la fila seleccionada."""
        dev_path = os.path.join(dev_root, row.path)
        repo_path = os.path.join(repo_root, row.path) if row.destination in ("principal", "addons") else ""
        dev_m = self._meta(dev_path)
        repo_m = self._meta(repo_path) if repo_path else {"existe": "sin destino"}
        self.summary.setPlainText("\n".join([
            f"Ruta: {row.path}",
            f"Dev: {dev_path}",
            f"Repositorio: {repo_path or '(sin destino)'}",
            f"Propietario: {row.owner}",
            f"Destino: {row.destination}",
            f"Estado A (Dev↔repo): {row.axis_a}",
            f"Estado B (Git): {row.axis_b}",
            f"Incidencias: {', '.join(row.incidences) or 'ninguna'}",
            f"Existencia Dev: {dev_m.get('existe')} / Repositorio: {repo_m.get('existe')}",
        ]))
        self.info.setPlainText(
            "[Dev]\n" + self._fmt(dev_m) + "\n\n[Repositorio]\n" + self._fmt(repo_m)
        )
        # Diferencias: reutilizar el motor existente.
        self._fill_diff(row, dev_path, repo_path)

    def _fill_diff(self, row: Row, dev_path: str, repo_path: str) -> None:
        from gipler.comparator import make_diff

        if not os.path.lexists(dev_path) or not os.path.lexists(repo_path):
            self.diff.set_texts("", "")
            self.diff.table.setRowCount(1)
            self.diff.table.setItem(0, 0, __import__("PySide6.QtWidgets", fromlist=["QTableWidgetItem"]).QTableWidgetItem(
                f"(no comparable: existe en Dev={os.path.lexists(dev_path)} / repo={os.path.lexists(repo_path)})"
            ))
            return
        d = make_diff(dev_path, repo_path)
        if d is None:
            self.diff.table.setRowCount(1)
            self.diff.table.setItem(0, 0, __import__("PySide6.QtWidgets", fromlist=["QTableWidgetItem"]).QTableWidgetItem(
                "(binario o symlink: sin diff textual — ver metadatos en Información)"
            ))
            return
        dev_text = ""
        repo_text = ""
        try:
            with open(os.devnull):  # no-op, las lecturas ya las hizo make_diff
                pass
        except Exception:
            pass
        with open(dev_path, encoding="utf-8") as f:
            dev_text = f.read()
        with open(repo_path, encoding="utf-8") as f:
            repo_text = f.read()
        self.diff.set_texts(dev_text, repo_text, left="Dev", right="Repositorio")

    def find_in_diff(self, text: str):
        return self.diff.find_first(text)
