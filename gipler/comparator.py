"""Fase 3 — Comparator (spec §5.2).

Eje A (Dev <-> repo): identical | new_in_dev | modified_in_dev |
missing_in_dev | not_comparable.
Eje B (Git, independiente): tracked_clean | tracked_modified | untracked | ignored.
La propiedad es un campo independiente. Diff textual bajo demanda.
"""
from __future__ import annotations

import difflib

from .scanner import Entry


def compare_pair(dev_e: Entry | None, repo_e: Entry | None) -> str | None:
    """Compara presencia física; None indica que no hay archivos en ninguno de los lados.

    Si el SHA-256 de alguno de los dos lados no se pudo calcular, el estado es
    `not_comparable`: nunca se infiere una modificación a partir de la ausencia
    de hash.
    """
    if dev_e is None or not dev_e.exists:
        if repo_e is None or not repo_e.exists:
            return None
        return "missing_in_dev"
    if repo_e is None or not repo_e.exists:
        return "new_in_dev"
    if not dev_e.sha256 or not repo_e.sha256:
        return "not_comparable"
    if dev_e.sha256 == repo_e.sha256:
        return "identical"
    return "modified_in_dev"


def make_diff(dev_abs: str, repo_abs: str, max_lines: int = 400) -> list[str] | None:
    """Diff unificado si ambos son texto; None si no aplica (binario/symlink)."""
    import os

    if os.path.islink(dev_abs) or os.path.islink(repo_abs):
        return None
    try:
        with open(dev_abs, encoding="utf-8", errors="strict") as f:
            a = f.read()
        with open(repo_abs, encoding="utf-8", errors="strict") as f:
            b = f.read()
    except (UnicodeDecodeError, OSError, ValueError):
        return None
    if len(a) > 2_000_000 or len(b) > 2_000_000:
        return None
    diff = list(
        difflib.unified_diff(
            b.splitlines(keepends=True),
            a.splitlines(keepends=True),
            fromfile="repo",
            tofile="dev",
        )
    )
    return diff[:max_lines]
