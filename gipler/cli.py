"""CLI del motor de análisis (solo lectura).

Uso:
  python -m gipler.cli analyze
      [--dev Dev] [--principal Repo] [--addons Repo] [--out INFORME] [--diff RUTA]
  python -m gipler.cli tui [--demo] [--dev Dev] [--principal Repo] [--addons Repo]
  python -m gipler.cli desktop [--uninstall] [--exec ORDEN] [--data-home DIR]
"""
from __future__ import annotations

import argparse
import os
import sys

from .analysis import analyze, diff_for
from .config import configured_paths


def _defaults() -> tuple[str, str, str]:
    return configured_paths()


def _add_paths(p: argparse.ArgumentParser, d_dev, d_main, d_add) -> None:
    p.add_argument("--dev", default=d_dev)
    p.add_argument("--principal", default=d_main)
    p.add_argument("--addons", default=d_add)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gipler-cli")
    sub = p.add_subparsers(dest="command", required=True)
    d_dev, d_main, d_add = _defaults()

    a = sub.add_parser("analyze", help="Informe de análisis (solo lectura)")
    _add_paths(a, d_dev, d_main, d_add)
    a.add_argument("--out", default="")
    a.add_argument("--diff", default="", help="Ruta para mostrar diff Dev vs repo")

    t = sub.add_parser("tui", help="Interfaz curses (análisis, navegación, selección, copias controladas)")
    _add_paths(t, d_dev, d_main, d_add)
    t.add_argument("--demo", action="store_true", help="Snapshot no interactivo")

    d = sub.add_parser("desktop", help="Instalar/eliminar lanzador .desktop e iconos hicolor")
    d.add_argument("--uninstall", action="store_true", help="Retira lo instalado")
    d.add_argument("--exec", dest="exec_cmd", default=None, help="Orden Exec del lanzador")
    d.add_argument("--data-home", default=None, help="Directorio XDG_DATA_HOME a usar")

    args = p.parse_args(argv)

    if args.command == "desktop":
        from . import resources

        if args.uninstall:
            removed = resources.uninstall_desktop(home=args.data_home)
            sys.stdout.write(
                "Retirado:\n" + "".join(f"  {p}\n" for p in removed or ["(nada)"])
            )
            return 0
        written = resources.install_desktop(exec_cmd=args.exec_cmd, home=args.data_home)
        sys.stdout.write("Instalado:\n" + "".join(f"  {p}\n" for p in written))
        return 0

    if args.command == "tui":
        from .tui import make_state, run_curses

        state = make_state(args.dev, args.principal, args.addons)
        if args.demo:
            for tab in ("principal", "addons", "sin determinar"):
                state.tab = tab
                print(state.render_list())
                print(state.render_detail())
            return 0
        if not run_curses(state):
            print("Sin terminal interactiva. Use --demo para inspeccionar.")
            print(state.render_list())
            print(state.render_detail())
        return 0

    text, rows, info = analyze(args.dev, args.principal, args.addons)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)

    if args.diff:
        from .comparator import make_diff

        dev_abs = os.path.join(args.dev, args.diff)
        # Prueba ambos repos: muestra diff contra el que tenga el archivo.
        for repo in (args.principal, args.addons):
            repo_abs = os.path.join(repo, args.diff)
            if os.path.exists(repo_abs) and os.path.exists(dev_abs):
                d = make_diff(dev_abs, repo_abs)
                if d:
                    sys.stdout.write("\n".join(d) + "\n")
                else:
                    sys.stdout.write("(sin diff textual: binario o symlink o idénticos)\n")
                break
    sys.stderr.write(
        "counts: "
        + ", ".join(f"{k}={v}" for k, v in info["counts"].items())
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
