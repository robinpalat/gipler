"""Cabecera de resumen de archivo (reutiliza los datos de Row)."""
from __future__ import annotations


def summary_text(row, dev_m: dict, repo_m: dict) -> str:
    from gipler.report import markers, state_detail

    mark = markers(row)
    detail = state_detail(row)
    lines = [
        f"Ruta: {row.path}",
        f"Propietario: {row.owner}",
        f"Destino: {row.destination}",
        f"Estado A (Dev↔repo): {row.axis_a}",
        f"Estado B (Git): {row.axis_b}",
        f"Incidencias: {', '.join(row.incidences) or 'ninguna'}",
        f"Dev: {dev_m.get('tipo', '')} size={dev_m.get('tamaño', '?')} {dev_m.get('permisos', '')} sha={str(dev_m.get('sha256', ''))[:12]}…",
        f"Repo: {repo_m.get('tipo', '')} size={repo_m.get('tamaño', '?')} {repo_m.get('permisos', '')} sha={str(repo_m.get('sha256', ''))[:12]}…",
    ]
    if mark:
        lines.append(f"Marcador: {mark}")
    if detail:
        lines.append(f"Detalle: {detail}")
    return "\n".join(lines)
