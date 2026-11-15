"""Cabecera de resumen de archivo (reutiliza los datos de Row)."""
from __future__ import annotations


def summary_text(row, dev_m: dict | None = None, repo_m: dict | None = None) -> str:
    """Resumen compacto de estado para la ventana Diff."""
    return "\n".join(
        [
            f"Estado A (Dev ↔ repo): {row.axis_a}",
            f"Estado B (Git): {row.axis_b}",
            f"Incidencias: {', '.join(row.incidences) or 'ninguna'}",
        ]
    )
