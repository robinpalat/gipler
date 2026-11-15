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
    """Selección segura según la política única de copia."""
    from gipler.copy_policy import static_row_blockers

    return not static_row_blockers(row)
