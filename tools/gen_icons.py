"""Genera los iconos empaquetados de Gipler desde el maestro `gipler.png`.

Uso:
    python tools/gen_icons.py

Produce, sin alterar el maestro:
    gipler/assets/gipler.png              (copia del maestro)
    gipler/assets/icons/<N>x<N>/apps/gipler.png   (jerarquía hicolor)
    gipler/assets/gipler.ico              (multi-tamaño, Windows/taskbar)
"""
from __future__ import annotations

import os
import shutil

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "gipler.png")
ASSETS = os.path.join(ROOT, "gipler", "assets")
ICONS = os.path.join(ASSETS, "icons")
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    if not os.path.exists(MASTER):
        raise SystemExit(f"no existe el maestro: {MASTER}")
    os.makedirs(ASSETS, exist_ok=True)
    shutil.copyfile(MASTER, os.path.join(ASSETS, "gipler.png"))

    with Image.open(MASTER) as src:
        full = src.convert("RGBA")

        for size in SIZES:
            out_dir = os.path.join(ICONS, f"{size}x{size}", "apps")
            os.makedirs(out_dir, exist_ok=True)
            with Image.new("RGBA", (size, size), (0, 0, 0, 0)) as canvas:
                tile = full.copy()
                tile.thumbnail((size, size), Image.LANCZOS)
                canvas.paste(tile, ((size - tile.width) // 2, (size - tile.height) // 2))
                canvas.save(os.path.join(out_dir, "gipler.png"), optimize=True)

        ico_path = os.path.join(ASSETS, "gipler.ico")
        full.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    print(f"iconos generados en {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
