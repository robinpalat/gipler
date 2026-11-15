"""Identidad canónica de selección y de fila.

La selección de copia se identifica por ``SelectionKey``:
``(destino_de_copia, ruta_relativa)``. Es la misma clave que consume el
motor de copia y no depende de la procedencia de la fila.

``RowRef`` identifica una fila visible para navegación/restauración:
``(fuente_de_la_fila, ruta_relativa)``. No se usa para autorizar ni para
decidir operaciones.
"""
from __future__ import annotations

from collections.abc import Iterable

SelectionKey = tuple[str, str]
RowRef = tuple[str, str]


def _valid_key(key) -> SelectionKey | None:
    if isinstance(key, tuple) and len(key) == 2:
        destination, path = key
        if (
            isinstance(destination, str)
            and destination
            and isinstance(path, str)
            and path
        ):
            return destination, path
    return None


def make_selection_key(
    destination_id: str | None, relative_path: str | None
) -> SelectionKey | None:
    """Construye una clave de selección válida o ``None``."""
    if not isinstance(destination_id, str) or not destination_id:
        return None
    if not isinstance(relative_path, str) or not relative_path:
        return None
    return destination_id, relative_path


def selection_key_for(row) -> SelectionKey | None:
    """Clave autoritativa de una fila; no hay fallback a procedencia."""
    if row is None:
        return None
    return _valid_key(getattr(row, "selection_key", None))


def selection_key_for_candidates(
    relative_path: str,
    source_id: str,
    eligible_destination_ids: Iterable[str],
) -> SelectionKey | None:
    """Clave para una fila de fuente según sus destinos elegibles."""
    eligible = tuple(eligible_destination_ids)
    if len(eligible) == 1:
        return make_selection_key(eligible[0], relative_path)
    if source_id in eligible:
        return make_selection_key(source_id, relative_path)
    return None


def selection_key_for_entry(entry) -> SelectionKey | None:
    """Clave para ``ProfileEntry``/TUI: solo si hay un destino único."""
    if entry is None:
        return None
    return make_selection_key(
        getattr(entry, "eligible_destination_source_id", None),
        getattr(entry, "path", None),
    )


def row_ref_for(row) -> RowRef | None:
    """Identidad visual de una fila; nunca es una clave de copia."""
    if row is None:
        return None
    source_id = getattr(row, "destination", None)
    path = getattr(row, "path", None)
    if (
        isinstance(source_id, str)
        and source_id
        and isinstance(path, str)
        and path
    ):
        return source_id, path
    return None


def selection_keys_for_path(
    keys: Iterable[SelectionKey], relative_path: str, is_dir: bool
) -> set[SelectionKey]:
    """Claves afectadas por excluir una ruta (archivo o directorio)."""
    base = str(relative_path or "").rstrip("/")
    if not base:
        return set(keys)
    if is_dir:
        prefix = base + "/"
        return {key for key in keys if key[1] == base or key[1].startswith(prefix)}
    return {key for key in keys if key[1] == base}
