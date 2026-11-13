"""Exclusión de archivos/carpetas desde la GUI (spec exclusión v1).

Configuración local, fuera del proyecto. La ruta por defecto es
`~/.config/Gipler/ignore.toml` (global, legado); cada perfil de Gipler
puede inyectar su propio archivo con el parámetro `path`, de modo que
las exclusiones pertenezcan al perfil y no a la aplicación entera.

No se guardan exclusiones en Dev ni en los repositorios, ni se toca
.gitignore. Sin Git de escritura.
"""
from __future__ import annotations

import os
import tomllib


def ignore_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "Gipler", "ignore.toml")


def _resolve(path: str | None = None) -> str:
    return path if path else ignore_path()


def load_patterns(path: str | None = None) -> list[str]:
    p = _resolve(path)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
        return list(data.get("exclude", {}).get("patterns", []))
    except Exception:
        return []


def save_patterns(patterns: list[str], path: str | None = None) -> None:
    path = _resolve(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[exclude]\npatterns = [\n")
        for pat in patterns:
            f.write(f'  "{pat}",\n')
        f.write("]\n")


def add_pattern(pattern: str, path: str | None = None) -> list[str]:
    patterns = load_patterns(path)
    if pattern not in patterns:
        patterns.append(pattern)
        save_patterns(patterns, path)
    return patterns


def remove_pattern(pattern: str, path: str | None = None) -> list[str]:
    """Retira una regla de exclusión (no toca ningún archivo del árbol)."""
    current = load_patterns(path)
    patterns = [p for p in current if p != pattern]
    if patterns != current:
        save_patterns(patterns, path)
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
