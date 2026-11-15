"""TUI de Gipler (basada exclusivamente en perfiles).

Navega y selecciona filas del análisis de un perfil sin reimplementar
Scanner, Recognition ni Comparator. El estado de navegación y selección
es solo en memoria (nunca se escribe a disco, no hay copias ni borrados).

Tecnología: curses de la stdlib.

Uso:
  python -m gipler.tui --profile ID [--demo]
  python -m gipler.cli tui --profile ID [--demo]
Teclas: ↑↓ navegar · [/] pestaña · f buscar · espacio marcar ·
s selección segura visible · p preparar · e autorizar+ejecutar ·
r actualizar · c limpiar · q salir
"""
from __future__ import annotations

import os

from .comparator import make_diff
from .profile import Profile, load_profile
from .profile_analysis import ProfileAnalysis, ProfileEntry, analyze_profile
from .recognition import MembershipState
from .selection import (
    SelectionKey,
    selection_key_for,
    selection_key_for_entry,
)


class ProfileState:
    """Terminal navigation for a persisted profile and its dynamic views."""

    def __init__(self, profile: Profile, analysis: ProfileAnalysis | None = None):
        self.profile = profile
        self.analysis = analysis or analyze_profile(profile)
        self.views = self._views()
        self.active_view = str(profile.view.get("active_tab", "inicio"))
        if self.active_view not in self.views:
            self.active_view = "inicio"
        self.cursor = 0
        self.search = ""
        self.selection: set[SelectionKey] = set()
        self.ops: list = []
        self.pending = False
        self.eligible_keys: set[tuple[str, str]] = set()
        self._refresh_eligibility()

    def _views(self) -> list[str]:
        return [
            "inicio",
            *(f"source:{source.id}" for source in sorted(self.profile.sources, key=lambda x: x.order)),
            "excluidos",
            "indeterminados",
        ]

    def view_label(self, view: str) -> str:
        if view == "inicio":
            return "Inicio"
        if view == "excluidos":
            return "Excluidos"
        if view == "indeterminados":
            return "Indeterminados"
        source_id = view.partition(":")[2]
        source = self.profile.source(source_id)
        return source.name if source else source_id

    def visible(self) -> list:
        if self.active_view == "inicio":
            rows = list(self.analysis.entries)
        elif self.active_view == "excluidos":
            rows = list(self.analysis.inventory.excluded)
        elif self.active_view == "indeterminados":
            rows = list(self.analysis.indeterminate)
        else:
            rows = list(self.analysis.source_entries.get(self.active_view.partition(":")[2], ()))
        if self.search:
            needle = self.search.casefold()
            rows = [row for row in rows if needle in row.path.casefold()]
        return rows

    def current(self):
        rows = self.visible()
        if not rows:
            return None
        self.cursor = max(0, min(self.cursor, len(rows) - 1))
        return rows[self.cursor]

    def move(self, delta: int) -> None:
        rows = self.visible()
        if rows:
            self.cursor = (self.cursor + delta) % len(rows)

    def change_view(self, delta: int) -> None:
        current = self.views.index(self.active_view)
        self.active_view = self.views[(current + delta) % len(self.views)]
        self.profile.view["active_tab"] = self.active_view
        self.cursor = 0

    def toggle(self) -> None:
        entry = self.current()
        if not isinstance(entry, ProfileEntry):
            return
        key = selection_key_for_entry(entry)
        if key is None or key not in self.eligible_keys:
            return
        if key in self.selection:
            self.selection.remove(key)
        else:
            self.selection.add(key)
        self.ops = []
        self.pending = False

    def select_safe_visible(self) -> None:
        from .copy_engine import build_operations

        visible_keys = {
            key
            for entry in self.visible()
            if (key := selection_key_for_entry(entry)) is not None
        }
        rows = [
            row for row in self.analysis.copy_rows()
            if selection_key_for(row) in visible_keys
        ]
        keys = {
            key
            for row in rows
            if (key := selection_key_for(row)) is not None
        }
        operations = build_operations(
            rows,
            keys,
            self.profile.work_dir,
            self.analysis.destination_roots,
            self.analysis.snapshot,
        )
        self.selection = {
            (operation.destination, operation.path)
            for operation in operations
            if operation.status == "copiable"
        }
        self.ops = []
        self.pending = False

    def prepare(self) -> list:
        from .copy_engine import build_operations

        self.ops = build_operations(
            self.analysis.copy_rows(),
            set(self.selection),
            self.profile.work_dir,
            self.analysis.destination_roots,
            self.analysis.snapshot,
        )
        self.pending = True
        return self.ops

    def authorize_and_execute(self) -> list[dict]:
        if not self.pending:
            return []
        from .copy_engine import execute_operations

        results = execute_operations(self.ops, authorized=True)
        self.pending = False
        self.refresh()
        return results

    def clear(self) -> None:
        self.selection.clear()
        self.ops = []
        self.pending = False

    def refresh(self) -> None:
        self.analysis = analyze_profile(self.profile)
        self._refresh_eligibility()
        self.selection.intersection_update(self.eligible_keys)
        self.ops = []
        self.pending = False
        self.views = self._views()
        if self.active_view not in self.views:
            self.active_view = "inicio"
        self.cursor = 0

    def _refresh_eligibility(self) -> None:
        from .copy_engine import build_operations

        rows = self.analysis.copy_rows()
        keys = {
            key
            for row in rows
            if (key := selection_key_for(row)) is not None
        }
        operations = build_operations(
            rows,
            keys,
            self.profile.work_dir,
            self.analysis.destination_roots,
            self.analysis.snapshot,
        )
        self.eligible_keys = {
            (operation.destination, operation.path)
            for operation in operations
            if operation.status == "copiable"
        }

    def render_profile_list(self) -> str:
        rows = self.visible()
        if rows:
            self.cursor = max(0, min(self.cursor, len(rows) - 1))
        lines = [
            f"=== Gipler TUI · {self.profile.name} · {self.view_label(self.active_view)} ===",
            f"elementos: {len(rows)} · selección de copia: {len(self.selection)}",
        ]
        if not rows and self.active_view == "excluidos":
            lines.append("Ningún archivo excluido")
        for index, entry in enumerate(rows):
            marker = ">>" if index == self.cursor else "  "
            physical = getattr(entry, "physical", entry)
            key = selection_key_for_entry(entry)
            checked = (
                "[x]" if key in self.selection
                else "[ ]" if key in self.eligible_keys
                else " - "
            )
            if isinstance(entry, ProfileEntry):
                state = entry.membership.state.value
                sources = ",".join(entry.membership.source_ids) or "ninguna"
                comparison = ""
                if self.active_view.startswith("source:"):
                    source_id = self.active_view.partition(":")[2]
                    row = next(
                        (
                            item for item in self.analysis.rows_by_source.get(source_id, ())
                            if item.path == entry.path
                        ),
                        None,
                    )
                    if row is not None:
                        comparison = f" | A={row.axis_a} B={row.axis_b}"
                lines.append(
                    f"{marker} {checked} {entry.path} | {physical.kind} | {state} | "
                    f"fuentes={sources}{comparison}"
                )
            else:
                rule = getattr(physical, "exclusion_rule", "")
                inherited = " · heredada" if getattr(physical, "exclusion_inherited", False) else ""
                lines.append(f"{marker} {physical.path} | {physical.kind}{' · ' + rule + inherited if rule else ''}")
        if self.ops:
            from .copy_engine import preview

            lines.append(preview(self.ops))
        return "\n".join(lines)

    def render_profile_detail(self) -> str:
        entry = self.current()
        if entry is None:
            return "(sin selección)"
        physical = getattr(entry, "physical", entry)
        path = os.path.join(self.profile.work_dir, *physical.path.split("/"))
        from .gui.inspector import Inspector

        metadata = Inspector._meta(path)
        lines = [
            f"Ruta: {physical.path}",
            f"Tipo: {physical.kind}",
            "Metadatos: " + ", ".join(f"{key}={value}" for key, value in metadata.items()),
        ]
        if isinstance(entry, ProfileEntry):
            lines.append(f"Pertenencia: {entry.membership.state.value}")
            lines.append("Fuentes: " + (", ".join(entry.membership.source_ids) or "ninguna"))
            lines.append(
                "Comparaciones: " + (", ".join(
                    f"{source_id}={state}" for source_id, state in entry.comparisons.items()
                ) or "sin contraparte")
            )
            if entry.copy_blockers:
                from .copy_policy import describe_blockers

                lines.append(
                    "Copia: " + "; ".join(describe_blockers(entry.copy_blockers))
                )
            if self.active_view.startswith("source:"):
                source_id = self.active_view.partition(":")[2]
                row = next(
                    (
                        item for item in self.analysis.rows_by_source.get(source_id, ())
                        if item.path == entry.path
                    ),
                    None,
                )
                if row is not None:
                    lines.extend(
                        [
                            f"Estado A: {row.axis_a}",
                            f"Estado B: {row.axis_b}",
                            "Incidencias: " + (", ".join(row.incidences) or "ninguna"),
                        ]
                    )
        if getattr(physical, "exclusion_rule", ""):
            inherited = " (heredada)" if physical.exclusion_inherited else ""
            lines.append(f"Exclusión: {physical.exclusion_rule}{inherited}")
        return "\n".join(lines)

    def render_list(self) -> str:
        return self.render_profile_list()

    def render_detail(self) -> str:
        return self.render_profile_detail()


def make_profile_state(profile_id: str) -> ProfileState:
    return ProfileState(load_profile(profile_id))


def run_profile_curses(state: ProfileState) -> bool:
    """Interactive profile TUI. Authorization remains a distinct explicit key."""
    try:
        import curses
    except ImportError:
        return False
    if not os.isatty(1):
        return False

    def main(stdscr):
        curses.curs_set(0)
        while True:
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            middle = max(10, height // 2)
            for y, line in enumerate(state.render_list().splitlines()[:middle]):
                try:
                    stdscr.addnstr(y, 0, line, width - 1)
                except Exception:
                    pass
            for y, line in enumerate(state.render_detail().splitlines()[:max(0, height - middle - 2)]):
                try:
                    stdscr.addnstr(middle + y, 0, line, width - 1)
                except Exception:
                    pass
            hints = "↑↓ navegar · [/] pestaña · f buscar · espacio marcar · s selección segura · p preparar · e autorizar+ejecutar · r actualizar · c limpiar · q salir"
            try:
                stdscr.addnstr(height - 1, 0, hints, width - 1)
            except Exception:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                break
            if key == curses.KEY_UP:
                state.move(-1)
            elif key == curses.KEY_DOWN:
                state.move(1)
            elif key in (ord("["), curses.KEY_LEFT):
                state.change_view(-1)
            elif key in (ord("]"), curses.KEY_RIGHT, 9):
                state.change_view(1)
            elif key in (ord("f"), ord("F")):
                try:
                    curses.echo()
                    stdscr.addnstr(height - 2, 0, "Buscar: ", max(1, width - 1))
                    stdscr.clrtoeol()
                    value = stdscr.getstr(height - 2, min(8, width - 1), max(1, width - 9))
                    state.search = value.decode("utf-8", errors="replace")
                    state.cursor = 0
                except curses.error:
                    state.search = ""
                finally:
                    curses.noecho()
            elif key == ord(" "):
                state.toggle()
            elif key in (ord("s"), ord("S")):
                state.select_safe_visible()
            elif key in (ord("p"), ord("P")):
                state.prepare()
            elif key in (ord("e"), ord("E")):
                state.authorize_and_execute()
            elif key in (ord("r"), ord("R")):
                state.refresh()
            elif key in (ord("c"), ord("C")):
                state.clear()

    curses.wrapper(main)
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="gipler-tui")
    p.add_argument("--demo", action="store_true", help="Snapshot no interactivo")
    p.add_argument("--profile", required=True, help="ID del perfil persistido")
    args = p.parse_args(argv)
    state = make_profile_state(args.profile)
    if args.demo:
        for view in state.views:
            state.active_view = view
            print(state.render_list())
            print(state.render_detail())
            print()
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
