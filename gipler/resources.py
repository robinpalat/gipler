"""Recursos gráficos y lanzador de escritorio (freedesktop.org).

El icono oficial vive dentro del paquete (`gipler/assets`) para que esté
disponible también con una instalación en site-packages. El lanzador
`.desktop` y los tamaños hicolor se instalan en los directorios XDG del
usuario con `install_desktop()`.
"""
from __future__ import annotations

import os
import shutil

ASSETS = os.path.dirname(os.path.abspath(__file__)) + os.sep + "assets"
APP_ID = "gipler"
WINDOW_CLASS = "Gipler"


def master_icon() -> str:
    """Icono maestro (original a máxima resolución)."""
    return os.path.join(ASSETS, "gipler.png")


def ico_path() -> str:
    """Icono multi-tamaño (Windows / usos que requieren .ico)."""
    return os.path.join(ASSETS, "gipler.ico")


def icon_path(size: int | None = None) -> str:
    """Ruta del icono; `size` selecciona un tamaño hicolor concreto."""
    if size is None:
        return master_icon()
    candidate = os.path.join(ASSETS, "icons", f"{size}x{size}", "apps", "gipler.png")
    return candidate if os.path.exists(candidate) else master_icon()


def available_sizes() -> list[int]:
    base = os.path.join(ASSETS, "icons")
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        head, sep, tail = name.partition("x")
        if not sep or not head.isdigit() or tail != head:
            continue
        if os.path.isfile(os.path.join(base, name, "apps", "gipler.png")):
            out.append(int(head))
    return out


def xdg_data_home() -> str:
    return os.path.expanduser(
        os.environ.get("XDG_DATA_HOME") or os.path.join("~", ".local", "share")
    )


def desktop_path() -> str:
    return os.path.join(xdg_data_home(), "applications", f"{APP_ID}.desktop")


def icon_install_dir(size: int) -> str:
    return os.path.join(xdg_data_home(), "icons", "hicolor", f"{size}x{size}", "apps")


def _default_exec() -> str:
    """Orden de preferencia para el `Exec` del lanzador."""
    project_runner = os.path.abspath(
        os.path.join(os.path.dirname(ASSETS), os.pardir, "run-gipler")
    )
    if os.path.isfile(project_runner) and os.access(project_runner, os.X_OK):
        return project_runner
    return shutil.which(f"{APP_ID}") or f"{APP_ID}"


def desktop_entry(exec_cmd: str | None = None) -> str:
    """Contenido del lanzador `.desktop` (XDG Desktop Entry Spec)."""
    exec_cmd = exec_cmd or _default_exec()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            "Name=Gipler",
            "GenericName=Directory comparison",
            "Comment=Analyze configured source and repository directories",
            f"Exec={exec_cmd} %F",
            f"Icon={APP_ID}",
            "Terminal=false",
            "Categories=Development;Utility;",
            "StartupNotify=true",
            f"StartupWMClass={WINDOW_CLASS}",
            "Keywords=git;diff;compare;sync;repository;",
            "",
        ]
    )


def _with_data_home(home: str | None, fn, *args, **kwargs):
    """Ejecuta `fn` forzando XDG_DATA_HOME a `home` si se indicó."""
    if home is None:
        return fn(*args, **kwargs)
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = home
    try:
        return fn(*args, **kwargs)
    finally:
        if old is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old


def install_desktop(exec_cmd: str | None = None, home: str | None = None) -> list[str]:
    """Instala `.desktop` + iconos hicolor en el directorio XDG del usuario.

    Devuelve la lista de rutas escritas. Nunca toca nada fuera de XDG_DATA_HOME.
    """
    return _with_data_home(home, _install, exec_cmd)


def _install(exec_cmd: str | None) -> list[str]:
    written: list[str] = []
    apps_dir = os.path.join(xdg_data_home(), "applications")
    os.makedirs(apps_dir, exist_ok=True)
    path = desktop_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(desktop_entry(exec_cmd))
    written.append(path)

    for size in available_sizes():
        target_dir = icon_install_dir(size)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{APP_ID}.png")
        shutil.copyfile(icon_path(size), target)
        written.append(target)

    refresh_icon_cache()
    return written


def uninstall_desktop(home: str | None = None) -> list[str]:
    """Elimina el lanzador y los iconos instalados por `install_desktop`."""
    return _with_data_home(home, _uninstall)


def _uninstall() -> list[str]:
    removed: list[str] = []
    path = desktop_path()
    if os.path.isfile(path):
        os.remove(path)
        removed.append(path)
    for size in available_sizes():
        target = os.path.join(icon_install_dir(size), f"{APP_ID}.png")
        if os.path.isfile(target):
            os.remove(target)
            removed.append(target)
    refresh_icon_cache()
    return removed


def refresh_icon_cache() -> None:
    """Invalida la caché de iconos si `gtk-update-icon-cache` está disponible."""
    binary = shutil.which("gtk-update-icon-cache")
    if not binary:
        return
    import subprocess

    hicolor = os.path.join(xdg_data_home(), "icons", "hicolor")
    for directory in (hicolor, os.path.expanduser("~/.icons")):
        if os.path.isdir(directory):
            subprocess.run(
                [binary, "-f", "-t", directory],
                capture_output=True,
                check=False,
            )
