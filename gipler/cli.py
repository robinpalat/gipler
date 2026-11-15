"""CLI de Gipler (basada exclusivamente en perfiles).

Uso:
  python -m gipler.cli analyze-profile PROFILE_ID [--out INFORME]
  python -m gipler.cli profile-list
  python -m gipler.cli tui --profile PROFILE_ID [--demo]
  python -m gipler.cli desktop [--uninstall] [--exec ORDEN] [--data-home DIR]
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gipler-cli")
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("analyze-profile", help="Informe de análisis comparativo de un perfil")
    pa.add_argument("profile_id")
    pa.add_argument("--out", default="")

    sub.add_parser("profile-list", help="Listar perfiles persistidos")

    t = sub.add_parser("tui", help="Interfaz curses de un perfil")
    t.add_argument("--profile", required=True, help="ID del perfil persistido")
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

    if args.command == "profile-list":
        from .profile import list_profiles

        profiles = list_profiles()
        if not profiles:
            sys.stdout.write("No hay perfiles.\n")
        for profile in profiles:
            sys.stdout.write(f"{profile.id}\t{profile.name}\t{profile.work_dir}\n")
        return 0

    if args.command == "analyze-profile":
        from .profile import load_profile
        from .profile_analysis import analyze_profile
        from .report import render_profile

        profile = load_profile(args.profile_id)
        result = analyze_profile(profile)
        source_names = {
            source.id: source.name
            for source in sorted(profile.sources, key=lambda item: item.order)
            if source.enabled
        }
        text = render_profile(
            profile.name,
            result.work_dir,
            source_names,
            result.rows_by_source,
        )
        inventory_lines = ["## Inventario físico (Inicio)"]
        for entry in result.entries:
            inventory_lines.append(
                f"{entry.path}\t{entry.kind}\t{entry.membership.state.value}\t"
                f"{','.join(entry.membership.source_ids) or 'sin reconocimiento'}"
            )
        inventory_lines.extend(["", "## Excluidos"])
        if not result.inventory.excluded:
            inventory_lines.append("Ningún archivo excluido")
        for entry in result.inventory.excluded:
            inherited = " (heredada)" if entry.exclusion_inherited else ""
            inventory_lines.append(
                f"{entry.path}\t{entry.exclusion_rule}{inherited}"
            )
        inventory_lines.extend(["", "## Indeterminados"])
        if not result.indeterminate:
            inventory_lines.append("Ningún archivo indeterminado")
        for entry in result.indeterminate:
            inventory_lines.append(
                f"{entry.path}\t{entry.membership.state.value}\t"
                f"{','.join(entry.membership.reasons)}"
            )
        text += "\n".join(inventory_lines) + "\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8") as file:
                file.write(text)
        else:
            sys.stdout.write(text)
        return 0

    from .tui import make_profile_state, run_profile_curses

    state = make_profile_state(args.profile)
    if args.demo:
        for view in state.views:
            state.active_view = view
            print(state.render_list())
            print(state.render_detail())
        return 0
    if not run_profile_curses(state):
        print("Sin terminal interactiva. Use --demo para inspeccionar.")
        for view in state.views:
            state.active_view = view
            print(state.render_list())
        print(state.render_detail())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
