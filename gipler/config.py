"""User configuration and non-destructive import of legacy preferences."""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QSettings

ORGANIZATION = "Gipler"
APPLICATION = "Gipler"
LEGACY_ORGANIZATION = "Idiomind"
LEGACY_APPLICATION = "IdiomindSync"


def _settings_directory(settings: QSettings) -> str:
    return os.path.dirname(settings.fileName())


def get_settings() -> QSettings:
    settings = QSettings(ORGANIZATION, APPLICATION)
    if not settings.value("migration/legacy_preferences_imported", False, type=bool):
        legacy = QSettings(LEGACY_ORGANIZATION, LEGACY_APPLICATION)
        for key in legacy.allKeys():
            if not settings.contains(key):
                settings.setValue(key, legacy.value(key))

        old_ignore = os.path.join(
            os.path.expanduser("~"), ".config", "idiomind-sync", "ignore.toml"
        )
        new_ignore = os.path.join(_settings_directory(settings), "ignore.toml")
        if os.path.isfile(old_ignore) and not os.path.exists(new_ignore):
            os.makedirs(os.path.dirname(new_ignore), exist_ok=True)
            shutil.copy2(old_ignore, new_ignore)

        settings.setValue("migration/legacy_preferences_imported", True)
        settings.sync()
    return settings


def default_paths() -> tuple[str, str, str]:
    home = os.path.expanduser("~")
    return (
        os.path.join(home, "Dev"),
        os.path.join(home, "Repositories", "Principal"),
        os.path.join(home, "Repositories", "Add-ons"),
    )


def configured_paths() -> tuple[str, str, str]:
    defaults = default_paths()
    settings = get_settings()
    return tuple(
        os.path.abspath(settings.value(f"paths/{key}", default))
        for key, default in zip(("dev", "principal", "addons"), defaults)
    )


def save_paths(dev: str, principal: str, addons: str) -> None:
    settings = get_settings()
    for key, path in zip(("dev", "principal", "addons"), (dev, principal, addons)):
        settings.setValue(f"paths/{key}", os.path.abspath(os.path.expanduser(path)))
    settings.sync()
