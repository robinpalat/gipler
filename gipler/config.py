"""Configuración de usuario (tema y preferencias de visualización).

Las rutas de comparación viven en los perfiles. Este módulo solo gestiona
las preferencias generales de la aplicación.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

ORGANIZATION = "Gipler"
APPLICATION = "Gipler"


def get_settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)
