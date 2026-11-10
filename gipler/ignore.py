"""Exclusión de archivos/carpetas desde la GUI (spec exclusión v1).

Configuración local, fuera del proyecto: ~/.config/gipler/ignore.toml
(devuelve vacío si no existe). No se guardan exclusiones en Dev ni en
los repositorios, ni se tocan .gitignore. Sin Git de escritura.
"""
from __future__ import annotations

import os
import tomllib


def ignore_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "Gipler", "ignore.toml")


def load_patterns() -> list[str]:
    p = ignore_path()
    if not os.path.isfile(p):
        return []
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
        return list(data.get("exclude", {}).get("patterns", []))
    except Exception:
        return []


def save_patterns(patterns: list[str]) -> None:
    path = ignore_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[exclude]\npatterns = [\n")
        for pat in patterns:
            f.write(f'  "{pat}",\n')
        f.write("]\n")


def add_pattern(pattern: str) -> list[str]:
    patterns = load_patterns()
    if pattern not in patterns:
        patterns.append(pattern)
    save_patterns(patterns)
    return patterns


def is_excluded(path: str, patterns: list[str]) -> bool:
    """True si path == patrón o está bajo un directorio patrón (‘dir/’)."""
    if not patterns:
        return False
    for pat in patterns:
        if not pat:
            continue
        if pat.endswith("/"):
            if path == pat.rstrip("/") or path.startswith(pat):
                return True
        elif path == pat or path.endswith("/" + pat) or path.startswith(pat + "/"):
            return True
    return False
