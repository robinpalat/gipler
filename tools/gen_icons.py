"""Genera los iconos empaquetados de Gipler desde el maestro Solid.

Uso:
    python tools/gen_icons.py [--source RUTA]

Produce, sin alterar el maestro:
    gipler/assets/icons/<N>x<N>/apps/gipler.png   (jerarquía hicolor)
    gipler/assets/gipler.ico                      (multi-tamaño, Windows/taskbar)
"""
from __future__ import annotations

import argparse
import os
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.path.join(ROOT, "gipler", "assets", "gipler_solid.png")
ASSETS = os.path.join(ROOT, "gipler", "assets")
ICONS = os.path.join(ASSETS, "icons")
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _same_file(first: str, second: str) -> bool:
    with open(first, "rb") as left, open(second, "rb") as right:
        while True:
            a = left.read(65536)
            b = right.read(65536)
            if a != b:
                return False
            if not a:
                return True


def _save_if_changed(image: Image.Image, path: str, **options) -> bool:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    suffix = os.path.splitext(path)[1]
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=suffix)
    os.close(descriptor)
    try:
        image.save(temporary, **options)
        if os.path.exists(path) and _same_file(temporary, path):
            return False
        os.replace(temporary, path)
        return True
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera los iconos de Gipler")
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help="PNG maestro Solid (por defecto: gipler/assets/gipler_solid.png)",
    )
    args = parser.parse_args(argv)

    source = os.path.abspath(args.source)
    if not os.path.isfile(source):
        raise SystemExit(f"no existe el icono maestro Solid: {source}")
    if not os.access(source, os.R_OK):
        raise SystemExit(f"el icono maestro Solid no es legible: {source}")

    try:
        with Image.open(source) as opened:
            full = opened.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"icono maestro Solid inválido: {exc}") from exc

    changed = 0
    unchanged = 0
    for size in SIZES:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tile = full.copy()
        tile.thumbnail((size, size), Image.LANCZOS)
        canvas.paste(tile, ((size - tile.width) // 2, (size - tile.height) // 2))
        target = os.path.join(ICONS, f"{size}x{size}", "apps", "gipler.png")
        if _save_if_changed(canvas, target, format="PNG", optimize=True):
            print(f"[actualizado] {_relative(target)}")
            changed += 1
        else:
            print(f"[sin cambios] {_relative(target)}")
            unchanged += 1
        canvas.close()
        tile.close()

    ico_path = os.path.join(ASSETS, "gipler.ico")
    if _save_if_changed(
        full,
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
    ):
        print(f"[actualizado] {_relative(ico_path)}")
        changed += 1
    else:
        print(f"[sin cambios] {_relative(ico_path)}")
        unchanged += 1

    print(f"Fuente Solid: {_relative(source)}")
    print(f"Resumen: {changed} actualizados, {unchanged} sin cambios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
