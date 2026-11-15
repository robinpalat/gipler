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
        selection_key: tuple[str, str] | None = None,
        copy_blockers: tuple[str, ...] = (),
        copy_status: str = "",
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
        self.selection_key = selection_key
        self.copy_blockers = tuple(copy_blockers)
        self.copy_status = copy_status

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
        m = markers(self)
        s = f"  {self.path}" + (f" [{m}]" if m else "")
        s += f"\n    dueño={self.owner} destino={self.destination} A={self.axis_a} B={self.axis_b}"
        if self.git_change or self.git_stage:
            s += f" git=[{self.git_change or 'sin detalle'} · {self.git_stage or 'sin fase'}]"
        if self.perm:
            s += f" permisos_dev_repo={self.perm}"
        if self.incidences:
            s += f" incidencias={','.join(self.incidences)}"
        if self.copy_blockers:
            from gipler.copy_policy import describe_blockers

            s += "\n    copia=" + "; ".join(describe_blockers(self.copy_blockers))
        for x in self.extra:
            s += f"\n    {x}"
        return s


def markers(row) -> str:
    """Marcadores ortogonales a los ejes (nunca alteran axis_a ni axis_b).

    `*`  → Dev y árbol de trabajo sincronizados con diferencia Git frente a HEAD.
    `⌀`  → diferencia exclusiva de permisos Dev→repo.
    """
    out = ""
    if getattr(row, "asterisk", False):
        out += "*"
    if getattr(row, "perm_marker", False):
        out += "⌀"
    return out


def state_detail(row) -> str:
    """Desglose para la columna de estado: Git (contenido · fase) y permisos.

    Devuelve "" cuando no hay nada que mostrar, de modo que la columna
    conserva exactamente `axis_b` en el caso normal.
    """
    parts: list[str] = []
    git_change = getattr(row, "git_change", "") or ""
    git_stage = getattr(row, "git_stage", "") or ""
    if git_change or git_stage:
        parts.append(git_change or "sin detalle")
        parts.append(git_stage or "sin fase")
    perm = getattr(row, "perm", "") or ""
    if perm:
        parts.append(f"⌀ {perm}")
    return " · ".join(parts)


def warnings_text(row) -> str:
    """Motivos visibles en la columna de advertencias."""
    blockers = getattr(row, "copy_blockers", ())
    if blockers:
        from gipler.copy_policy import describe_blockers

        return "; ".join(describe_blockers(blockers))
    return ",".join(row.incidences)


def tooltip_text(row) -> str:
    """Detalle completo para tooltips (GUI y TUI)."""
    m = markers(row)
    d = state_detail(row)
    out = f"{row.path}\n{row.owner} -> {row.destination} | A={row.axis_a} B={row.axis_b}"
    if m:
        out += f"\nMarcador: {m}"
    if d:
        out += f"\nDetalle: {d}"
    if row.incidences:
        out += f"\nIncidencias: {','.join(row.incidences)}"
    blockers = getattr(row, "copy_blockers", ())
    if blockers:
        from gipler.copy_policy import describe_blockers

        out += "\nCopia: " + "; ".join(describe_blockers(blockers))
    return out


def render_profile(
    profile_name: str,
    work_dir: str,
    source_names: dict[str, str],
    rows_by_source: dict[str, tuple[Row, ...]],
) -> str:
    """Render comparison results using configured source identities and labels."""
    out = [
        f"# Gipler — informe de análisis · {profile_name}",
        f"Directorio de trabajo: {work_dir}",
        "Análisis de solo lectura; no se ejecutaron operaciones.",
        "",
    ]
    for source_id, name in source_names.items():
        rows = list(rows_by_source.get(source_id, ()))
        counts = {
            state: sum(row.axis_a == state for row in rows)
            for state in (
                "new_in_dev",
                "modified_in_dev",
                "identical",
                "missing_in_dev",
                "not_comparable",
            )
        }
        out.append(f"## {name} [{source_id}] ({len(rows)} archivos)")
        out.append(
            "Estados: "
            + ", ".join(f"{state}={count}" for state, count in counts.items())
        )
        out.extend(row.line() for row in rows)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
