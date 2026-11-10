"""Orquestación Scanner -> Classifier -> Comparator -> Report (solo lectura)."""
from __future__ import annotations

import os

from . import scanner as _scan
from .classifier import classify, load_exclusions, parse_manifests
from .comparator import compare_pair
from .report import Row, render

REPO_DIRS = {"principal": None, "addons": None}  # se fijan con rutas reales


def _perm_diff(dev_mode: int, repo_mode: int) -> str:
    """Detalle de diferencia de permisos Dev→repo (informativo, nunca azul)."""
    text = f"{oct(dev_mode)[2:]}→{oct(repo_mode)[2:]}"
    if bool(dev_mode & 0o111) != bool(repo_mode & 0o111):
        text += " · bit ejecutable"
    return text


def analyze(dev: str, principal: str, addons: str) -> tuple[str, list[Row], dict]:
    from .ignore import is_excluded, load_patterns

    dev = os.path.abspath(dev)
    principal = os.path.abspath(principal)
    addons = os.path.abspath(addons)
    repos = {"principal": principal, "addons": addons}

    dev_entries = _scan.scan_tree(dev, git=False)
    repo_entries = {
        name: _scan.scan_tree(path, git=True) for name, path in repos.items()
    }

    excluded_patterns = load_patterns()
    if excluded_patterns:
        for p in list(dev_entries):
            if is_excluded(p, excluded_patterns):
                del dev_entries[p]
        for name in repo_entries:
            for p in list(repo_entries[name]):
                if is_excluded(p, excluded_patterns):
                    del repo_entries[name][p]

    manifests = parse_manifests(dev)
    patterns, devsync_warn = load_exclusions(dev)

    # Duplicación decidida images/img.11.png: presente en ambos repos.
    # Se informa sin modificarla; el código refleja el estado real
    # (tracked en ambos vs. presente con otro estado Git en uno de ellos).
    dup_codes: dict[str, str] = {}
    p11 = "images/img.11.png"
    if p11 in repo_entries.get("principal", {}) and p11 in repo_entries.get("addons", {}):
        if repo_entries["principal"][p11].git_state in ("tracked_clean", "tracked_modified") and repo_entries["addons"][p11].git_state in ("tracked_clean", "tracked_modified"):
            dup_codes[p11] = "duplicate_tracked_in_both"
        else:
            dup_codes[p11] = "present_in_both_repos"

    classifications = classify(
        dev, set(dev_entries), manifests, patterns, duplicate_codes=dup_codes
    )

    # Symlinks externos en Dev -> incidencia (spec §7.8).
    symlink_inc: dict[str, str] = {}
    for path, e in dev_entries.items():
        if e.is_symlink and _scan.symlink_scope(dev, path, e) == "external":
            symlink_inc[path] = "symlink_escapes_allowed_dirs"

    # Estado B de rutas ausentes en cada repo (lote).
    rows: list[Row] = []
    seen: set[tuple[str, str]] = set()

    def add_row(path: str, c, dest: str) -> None:
        key = (dest, path)
        if key in seen:
            return
        seen.add(key)
        incidences: list[str] = list(c.incidences) if c else []
        if path in symlink_inc:
            incidences.append(symlink_inc[path])
        extra: list[str] = []
        if c is not None and c.context:
            extra.append(f"contexto={c.context}")
        if c is not None and c.excluded:
            extra.append("excluido por dev-sync.toml")
        if path == p11:
            extra.append(
                "también presente en el otro repositorio (duplicación informada, sin modificar)"
            )
        dev_e = dev_entries.get(path)
        dest_entries = repo_entries.get(dest, {}) if dest else {}
        repo_e = dest_entries.get(path)
        if dest and repo_e is None:
            # Ausente en disco en el repo: B via check-ignore del repo.
            axis_b = _scan.git_state_for_absent(repos[dest], path) if dest in repos else "untracked"
            repo_e_absent = None
        else:
            axis_b = repo_e.git_state if repo_e is not None else ""
            repo_e_absent = repo_e
        axis_a = compare_pair(dev_e, repo_e_absent)
        if axis_a is None:
            if not incidences:
                return
            axis_a = "n/a"
        if axis_b == "":
            axis_b = "n/a"
        # Manifiesto declara algo ignorado en su destino -> discrepancia visible.
        if dest and axis_b == "ignored" and c is not None and c.owner not in ("", "núcleo"):
            if "manifest_vs_git_discrepancy" not in incidences:
                incidences.append("manifest_vs_git_discrepancy")
        owner = c.owner if c is not None else ""
        if dev_e is None and repo_e is not None and repo_e.exists and repo_e.git_state in (
            "tracked_clean",
            "tracked_modified",
        ):
            # Huérfano del repo: sin correspondencia en Dev.
            axis_a = "missing_in_dev"
        # Desglose Git (independiente de axis_b) y permisos Dev→repo (independiente
        # de axis_a): ni el marcador de permisos ni el detalle alteran el eje A.
        git_change = repo_e.git_change if repo_e is not None else ""
        git_stage = repo_e.git_stage if repo_e is not None else ""
        perm = ""
        if (
            dev_e is not None
            and dev_e.exists
            and repo_e is not None
            and repo_e.exists
            and not dev_e.is_symlink
            and not repo_e.is_symlink
            and dev_e.mode != repo_e.mode
        ):
            perm = _perm_diff(dev_e.mode, repo_e.mode)
        rows.append(
            Row(
                path, owner, dest, axis_a, axis_b, incidences, extra,
                git_change=git_change, git_stage=git_stage, perm=perm,
            )
        )

    # 1) Todas las rutas clasificadas de Dev (incluidas declaradas ausentes).
    for path, c in classifications.items():
        if c.excluded and path not in dev_entries and c.owner == "":
            continue  # excluido y ausente: ruido
        add_row(path, c, c.destination)

    # 2) Archivos del repo sin clasificación / huérfanos del repo.
    for dest, entries in repo_entries.items():
        for path, e in entries.items():
            c = classifications.get(path)
            if c is None or (c.destination != dest and (c.owner == "" or c.owner == "núcleo" and dest != "principal")):
                if path in dev_entries:
                    continue  # ya procesado en (1)
                add_row(path, c or None, dest)

    # 3) Dev sin dueño y con destino asignado por núcleo ya cubierto en (1).

    warnings: list[str] = []
    if devsync_warn:
        warnings.append(
            "dev-sync.toml no existe en Dev (devsync_missing): sin exclusiones."
        )
    meta = {"dev": dev, "principal": principal, "addons": addons}
    counts = {
        "rows": len(rows),
        "new_in_dev": sum(1 for r in rows if r.axis_a == "new_in_dev"),
        "modified_in_dev": sum(1 for r in rows if r.axis_a == "modified_in_dev"),
        "identical": sum(1 for r in rows if r.axis_a == "identical"),
        "missing_in_dev": sum(1 for r in rows if r.axis_a == "missing_in_dev"),
        "not_comparable": sum(1 for r in rows if r.axis_a == "not_comparable"),
        "tracked_modified": sum(1 for r in rows if r.axis_b == "tracked_modified"),
        "ignored": sum(1 for r in rows if r.axis_b == "ignored"),
        "perm_diff": sum(1 for r in rows if r.perm),
        "git_change_content": sum(1 for r in rows if r.git_change in ("contenido", "contenido+permisos")),
        "git_change_mode": sum(1 for r in rows if r.git_change in ("permisos", "contenido+permisos")),
        "git_staged": sum(1 for r in rows if r.git_stage in ("staged", "staged+unstaged")),
        "incidences": sum(1 for r in rows for _ in r.incidences),
    }
    text = render(meta, rows, warnings)
    return text, rows, {
        "meta": meta,
        "warnings": warnings,
        "counts": counts,
        "snapshot": {
            # Huella mínima del análisis para re-check de copy_engine
            # (no es lógica nueva: expone lo ya escaneado).
            "dev": {p: e.sha256 for p, e in dev_entries.items()},
            "repos": {
                name: {p: e.sha256 for p, e in entries.items()}
                for name, entries in repo_entries.items()
            },
        },
    }


def diff_for(dev: str, repos: dict[str, str], path: str, destination: str):
    """Diff textual bajo demanda para un archivo (Fase 3)."""
    from .comparator import make_diff

    dev_e = os.path.join(dev, path)
    repo_e = os.path.join(repos[destination], path)
    return make_diff(dev_e, repo_e)
