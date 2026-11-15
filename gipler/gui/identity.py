"""Identidad visual centralizada para ventanas y diálogos de Gipler.

Todas las ventanas de nivel superior resuelven su icono desde
`gipler.resources.master_icon()`, única fuente de verdad de la aplicación.
"""
from __future__ import annotations

import os
from functools import lru_cache

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from gipler.resources import master_icon


@lru_cache(maxsize=1)
def application_icon() -> QIcon:
    """QIcon de la identidad principal (Solid), o uno vacío si no existe."""
    path = master_icon()
    return QIcon(path) if os.path.isfile(path) else QIcon()


def apply_window_icon(window: QWidget) -> None:
    """Aplica la identidad principal a una ventana o diálogo."""
    icon = application_icon()
    if not icon.isNull():
        window.setWindowIcon(icon)


def clear_cache() -> None:
    """Olvida el QIcon resuelto (por ejemplo, tras actualizar los recursos)."""
    application_icon.cache_clear()
