"""Exclusiones de perfiles (formato TOML compartido).

Cada perfil almacena sus reglas en `exclusions.toml`. Este módulo provee la
serialización/lectura de bajo nivel y la comprobación de rutas. No define
rutas globales: el llamador proporciona la del perfil, de modo que las
exclusiones globales y las de perfil nunca se mezclan.

La serialización usa cadenas básicas TOML con escape correcto y la escritura
es atómica (temporal exclusivo + fsync + validación + replace + fsync del
directorio). Un archivo existente pero corrupto genera `PatternsError`; nunca
se interpreta silenciosamente como una lista vacía.
"""
from __future__ import annotations

import os
import tempfile
import tomllib


class PatternsError(ValueError):
    """Reglas de exclusión ilegibles, corruptas o no serializables."""


def _escape_string(value: str) -> str:
    """Serializa `value` como cadena básica TOML con escape correcto."""
    out = ['"']
    for char in value:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\b":
            out.append("\\b")
        elif char == "\t":
            out.append("\\t")
        elif char == "\n":
            out.append("\\n")
        elif char == "\f":
            out.append("\\f")
        elif char == "\r":
            out.append("\\r")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def dump_patterns(patterns: list[str]) -> str:
    """Genera TOML válido para `[exclude].patterns` sin concatenación insegura."""
    lines = ["[exclude]", "patterns = ["]
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise PatternsError(f"patrón de exclusión no textual: {pattern!r}")
        lines.append(f"  {_escape_string(pattern)},")
    lines.append("]")
    return "\n".join(lines) + "\n"


def _validate_patterns_text(text: str, path: str, expected: list[str]) -> None:
    """Comprueba que el texto generado vuelve a interpretarse igual."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PatternsError(f"exclusiones TOML inválidas para {path}: {exc}") from exc
    exclude = data.get("exclude")
    if not isinstance(exclude, dict) or not isinstance(exclude.get("patterns"), list):
        raise PatternsError(f"estructura [exclude].patterns inválida en {path}")
    if exclude["patterns"] != expected:
        raise PatternsError(
            f"las exclusiones serializadas no coinciden con las esperadas en {path}"
        )


def _fsync_directory(directory: str) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def write_atomic(path: str, text: str, *, validate=None) -> None:
    """Escritura atómica dentro del mismo directorio.

    1) temporal exclusivo, 2) escritura completa, 3) flush + fsync,
    4) validación opcional, 5) os.replace, 6) fsync del directorio.
    Si algo falla antes del reemplazo, el archivo anterior queda intacto.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=directory, prefix=".tmp-", suffix=".toml"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        if validate is not None:
            validate(text, path)
        os.replace(temporary, path)
        _fsync_directory(directory)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def save_patterns(patterns: list[str], path: str) -> None:
    """Serializa y persiste las reglas de forma atómica y validada."""
    text = dump_patterns(patterns)
    expected = list(patterns)
    write_atomic(
        path,
        text,
        validate=lambda candidate, target: _validate_patterns_text(
            candidate, target, expected
        ),
    )


def load_patterns(path: str) -> list[str]:
    """Carga las reglas de exclusión.

    Un archivo inexistente representa legítimamente que aún no hay reglas.
    Un archivo existente pero ilegible o inválido genera `PatternsError`
    identificando la ruta; nunca se convierte en una lista vacía.
    """
    if not os.path.lexists(path):
        return []
    try:
        with open(path, "rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise PatternsError(f"TOML ilegible en {path}: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise PatternsError(f"no se pudo leer {path}: {exc}") from exc
    exclude = data.get("exclude")
    if not isinstance(exclude, dict) or not isinstance(exclude.get("patterns"), list):
        raise PatternsError(f"estructura [exclude].patterns inválida en {path}")
    patterns = exclude["patterns"]
    if any(not isinstance(pattern, str) for pattern in patterns):
        raise PatternsError(f"patrón de exclusión no textual en {path}")
    return list(patterns)


def add_pattern(pattern: str, path: str) -> list[str]:
    """Añade una regla. Si el archivo es corrupto, falla sin sobrescribirlo."""
    patterns = load_patterns(path)
    if pattern not in patterns:
        patterns.append(pattern)
        save_patterns(patterns, path)
    return patterns


def remove_pattern(pattern: str, path: str) -> list[str]:
    """Retira una regla de exclusión (no toca ningún archivo del árbol)."""
    current = load_patterns(path)
    patterns = [p for p in current if p != pattern]
    if patterns != current:
        save_patterns(patterns, path)
    return patterns


def is_excluded(path: str, patterns: list[str]) -> bool:
    """True si path == patrón o está bajo un directorio patrón ('dir/')."""
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
