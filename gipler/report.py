"""Fase 4 — Informe (spec §8, Fase 4 del encargo).

Texto legible agrupado: 1 principal, 2 addons, 3 nuevos, 4 modificados,
5 idénticos, 6 modificaciones locales, 7 ignorados, 8 huérfanos,
9 ambigüedades e incidencias.
"""
from __future__ import annotations


class Row:
    def __init__(
        self,
        path: str,
        owner: str,
        destination: str,
        axis_a: str,
        axis_b: str,
        incidences: list[str],
        extra: list[str] | None = None,
        git_change: str = "",
        git_stage: str = "",
        perm: str = "",
    ):
        self.path = path
        self.owner = owner or "sin determinar"
        self.destination = destination or "sin determinar"
        self.axis_a = axis_a
        self.axis_b = axis_b
        self.incidences = incidences
        self.extra = extra or []
        # Desglose orthogonal (no altera axis_a ni axis_b):
        self.git_change = git_change  # contenido | permisos | contenido+permisos
        self.git_stage = git_stage    # staged | unstaged | staged+unstaged
        self.perm = perm              # permisos Dev→repo, vacío si coinciden

    @property
    def asterisk(self) -> bool:
        """Dev y árbol de trabajo sincronizados, con diferencia Git frente a HEAD.

        No implica «pendiente de commit»: el pendiente puede estar staged,
        unstaged o en ambos.
        """
        return self.axis_a == "identical" and self.axis_b == "tracked_modified"

    @property
    def perm_marker(self) -> bool:
        """Diferencia exclusiva de permisos Dev→repo (no toca axis_a ni color)."""
        return bool(self.perm)

    def line(self) -> str:
        s = f"  {self.path}\n    dueño={self.owner} destino={self.destination} A={self.axis_a} B={self.axis_b}"
        if self.git_change or self.git_stage:
            s += f" git=[{self.git_change or 'sin detalle'} · {self.git_stage or 'sin fase'}]"
        if self.perm:
            s += f" permisos_dev_repo={self.perm}"
        if self.incidences:
            s += f" incidencias={','.join(self.incidences)}"
        for x in self.extra:
            s += f"\n    {x}"
        return s


def _counted(rows, pred) -> list[Row]:
    return [r for r in rows if pred(r)]


def render(meta: dict, rows: list[Row], warnings: list[str]) -> str:
    out: list[str] = []
    out.append("# Gipler — informe de análisis (solo lectura, sin copias)")
    out.append(f"Dev: {meta.get('dev', '')}")
    out.append(f"Principal: {meta.get('principal', '')}")
    out.append(f"Addons: {meta.get('addons', '')}")
    for w in warnings:
        out.append(f"AVISO: {w}")
    n = len(rows)
    out.append(f"Total filas: {n}")
    out.append("")

    def section(title: str, filtered: list[Row]) -> None:
        out.append(f"## {title} ({len(filtered)})")
        for r in filtered:
            out.append(r.line())
        out.append("")

    by_repo = lambda d: [r for r in rows if r.destination == d]
    section("1. Repositorio principal", by_repo("principal"))
    section("2. Repositorio de addons", by_repo("addons"))
    section("3. Archivos nuevos (new_in_dev)", _counted(rows, lambda r: r.axis_a == "new_in_dev"))
    section("4. Archivos modificados (modified_in_dev)", _counted(rows, lambda r: r.axis_a == "modified_in_dev"))
    section("4b. No comparables (not_comparable)", _counted(rows, lambda r: r.axis_a == "not_comparable"))
    section("4c. Diferencia de permisos Dev→repo (⌀)", _counted(rows, lambda r: bool(r.perm)))
    section("5. Archivos idénticos (identical)", _counted(rows, lambda r: r.axis_a == "identical"))
    section("6. Modificaciones locales (tracked_modified)", _counted(rows, lambda r: r.axis_b == "tracked_modified"))
    section("7. Ignorados (ignored)", _counted(rows, lambda r: r.axis_b == "ignored"))
    section("8. Huérfanos (missing_in_dev / manifest_undeclared_file)", _counted(
        rows,
        lambda r: r.axis_a == "missing_in_dev" or "manifest_undeclared_file" in r.incidences,
    ))
    ambiguous = _counted(
        rows,
        lambda r: (
            r.destination in ("", "sin determinar")
            or "shared_file" in r.incidences
            or "status_unrecognized" in r.incidences
            or "status_development" in r.incidences
            or "unknown_owner" in r.incidences
            or "external_dependency" in r.incidences
            or "path_outside_prefix" in r.incidences
            or "symlink_escapes_allowed_dirs" in r.incidences
            or "manifest_missing_file" in r.incidences
            or "manifest_vs_git_discrepancy" in r.incidences
            or "duplicate_tracked_in_both" in r.incidences
            or "present_in_both_repos" in r.incidences
        ),
    )
    section("9. Ambigüedades e incidencias", ambiguous)
    sin_destino = [r for r in rows if r.destination in ("", "sin determinar")]
    if sin_destino:
        out.append(f"## 10. Sin destino (sin determinar) ({len(sin_destino)})")
        for r in sin_destino:
            out.append(r.line())
        out.append("")
    return "\n".join(out) + "\n"
