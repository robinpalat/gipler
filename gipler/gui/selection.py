"""Controlador de selección lógica (Fase 4, spec GUI §6).

Única fuente de selección compartida por ambos exploradores. La
selección es intención, no autorización: no escribe nada. Claves con
forma (destination, path), iguales a las de copy_engine.
"""
from __future__ import annotations


class SelectionController:
    def __init__(self):
        self.keys: set[tuple[str, str]] = set()

    def toggle(self, key: tuple[str, str]) -> None:
        (self.keys.discard if key in self.keys else self.keys.add)(key)

    def add(self, key: tuple[str, str]) -> None:
        self.keys.add(key)

    def discard(self, key: tuple[str, str]) -> None:
        self.keys.discard(key)

    def clear(self) -> None:
        self.keys.clear()

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self.keys

    def __len__(self) -> int:
        return len(self.keys)


def is_safe(row) -> bool:
    """Criterio interactivo de selección segura (TUI, sin duplicar
    clasificaciones del motor): propietario/destino conocidos, sin
    incidencias bloqueantes, sin tracked_modified ni ignored."""
    if row.destination not in ("principal", "addons"):
        return False
    if not row.owner or row.owner == "sin determinar":
        return False
    if row.axis_b in ("tracked_modified", "ignored"):
        return False
    bad = {
        "shared_file", "status_unrecognized", "status_development",
        "unknown_owner", "ambiguous", "external_dependency",
        "path_outside_prefix", "symlink_escapes_allowed_dirs", "excluded",
    }
    return not (bad & set(row.incidences))
