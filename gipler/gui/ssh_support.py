"""Integración de Gipler con el cliente SSH del sistema.

No gestiona claves ni passphrases: sólo prepara el entorno para que OpenSSH
pueda usar su mecanismo askpass gráfico cuando la clave privada está protegida.
El cliente SSH, la configuración del usuario y SSH_AUTH_SOCK se conservan.
"""
from __future__ import annotations

import os
import shlex
import sys
import tempfile

from PySide6.QtCore import QStandardPaths


def gui_available(env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    if values.get("QT_QPA_PLATFORM") in ("offscreen", "minimal"):
        return False
    return bool(values.get("DISPLAY") or values.get("WAYLAND_DISPLAY"))


def askpass_helper_path() -> str | None:
    """Return an executable launcher for the embedded Qt askpass helper."""
    source = os.path.join(os.path.dirname(__file__), "ssh_askpass.py")
    if not os.path.isfile(source):
        return None
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    if not base:
        base = tempfile.gettempdir()
    directory = os.path.join(base, "gipler")
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        target = os.path.join(directory, "ssh-askpass")
        content = (
            "#!/bin/sh\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(source)} \"$@\"\n"
        )
        try:
            with open(target, encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            current = ""
        if current != content:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(target, 0o700)
        return target
    except OSError:
        return None


def configure_askpass(env: dict[str, str]) -> dict[str, str]:
    """Return *env* with a graphical SSH askpass configured when possible.

    An existing SSH_ASKPASS or SSH_ASKPASS_REQUIRE is respected.  When there is
    no graphical session the environment is left untouched and OpenSSH will
    report its normal authentication failure.
    """
    result = dict(env)
    if not gui_available(result):
        return result
    askpass = (result.get("SSH_ASKPASS") or "").strip()
    if not askpass:
        askpass = askpass_helper_path() or ""
    if not askpass:
        return result
    result["SSH_ASKPASS"] = askpass
    result.setdefault("SSH_ASKPASS_REQUIRE", "force")
    return result
