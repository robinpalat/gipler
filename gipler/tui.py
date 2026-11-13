"""Segunda etapa — TUI (spec §8, inspirada en Meld).

Consume las filas de analysis.analyze() sin reimplementar Scanner,
Classifier ni Comparator. Estado de navegación y selección en memoria
solo (nunca se escribe a disco, no hay copias ni borrados).

Tecnología: curses de la stdlib (sin dependencias instalables).
Textual no está instalado; Rich sí, pero curses es la opción ligera y
mantenible para esta navegación.

Uso:
  python -m gipler.tui                # modo interactivo real
  python -m gipler.cli tui            # equivalente vía CLI
  python -m gipler.tui --demo         # snapshot no interactivo
Teclas: ↑↓ navegar · 1/2/3 repo/vista · f filtro · espacio marcar ·
s selección segura visible · p preparar · e autorizar+ejecutar ·
r reanalizar tras copias · c limpiar · q salir
"""
from __future__ import annotations

import os

from .analysis import analyze
from .comparator import make_diff
from .profile import Profile, load_profile
from .profile_analysis import ProfileAnalysis, ProfileEntry, analyze_profile
from .recognition import MembershipState
from .report import markers, state_detail

TABS = ("principal", "addons", "sin determinar")

FILTERS = (
    ("todos", "Todos"),
    ("new_in_dev", "Nuevos en Dev"),
    ("modified_in_dev", "Modificados en Dev"),
    ("identical", "Idénticos"),
    ("tracked_modified", "Modificados localmente"),
    ("ignored", "Ignorados por Git"),
    ("missing_in_dev", "Ausentes en Dev"),
    ("not_comparable", "No comparables"),
    ("permisos", "Diferencia de permisos Dev→repo"),
    ("incidencias", "Con incidencias"),
)

SAFE_B = {"tracked_modified"}


class State:
    def __init__(self, rows: list, meta: dict, warnings: list[str], snapshot: dict | None = None):
        self.rows = rows
        self.meta = meta
        self.warnings = warnings
        self.snapshot = snapshot or {"dev": {}, "repos": {}}
        self.ops: list = []
        self.results: list[dict] = []
        self.pending = False  # operaciones preparadas, pendientes de autorización
        self.tab = "principal"
        self.filter_key = "todos"
        self.cursor = 0
        self.selection: set[tuple[str, str]] = set()

    # -- filtrado ----------------------------------------------------
    def visible(self) -> list:
        base = [r for r in self.rows if r.destination == self.tab]
        k = self.filter_key
        if k == "todos":
            return base
        if k == "incidencias":
            return [r for r in base if r.incidences]
        if k == "permisos":
            return [r for r in base if getattr(r, "perm", "")]
        if k.startswith("tracked_") or k == "ignored":
            return [r for r in base if r.axis_b == k]
        return [r for r in base if r.axis_a == k]

    def current(self):
        vis = self.visible()
        if not vis:
            return None
        self.cursor = max(0, min(self.cursor, len(vis) - 1))
        return vis[self.cursor]

    def move(self, delta: int) -> None:
        vis = self.visible()
        if vis:
            self.cursor = (self.cursor + delta) % len(vis)

    # -- selección (solo memoria) ------------------------------------
    def toggle(self) -> None:
        r = self.current()
        if r is None:
            return
        key = (r.destination, r.path)
        self.selection.discard(key) if key in self.selection else self.selection.add(key)

    @staticmethod
    def is_safe(row) -> bool:
        if row.destination not in ("principal", "addons"):
            return False
        if row.axis_b in SAFE_B or row.axis_b == "ignored":
            return False
        bad = {
            "shared_file", "status_unrecognized", "status_development",
            "unknown_owner", "ambiguous", "external_dependency",
            "path_outside_prefix", "symlink_escapes_allowed_dirs",
        }
        if row.owner == "sin determinar" or not row.owner:
            return False
        return not (bad & set(row.incidences))

    def select_safe_visible(self) -> None:
        for r in self.visible():
            if self.is_safe(r):
                self.selection.add((r.destination, r.path))

    def clear(self) -> None:
        self.selection.clear()
        self.ops = []
        self.results = []
        self.pending = False

    def refresh(self) -> str:
        """Re-ejecuta el análisis (tras copias) sin reiniciar.
        Limpia selección y operaciones pendientes; devuelve mensaje."""
        from .analysis import analyze

        _, rows, info = analyze(
            self.meta.get("dev", ""), self.meta.get("principal", ""), self.meta.get("addons", "")
        )
        self.rows = rows
        self.meta = info["meta"]
        self.warnings = info["warnings"]
        self.snapshot = info.get("snapshot", {"dev": {}, "repos": {}})
        self.selection.clear()
        self.ops = []
        self.results = []
        self.pending = False
        self.cursor = 0
        return f"Análisis actualizado: {len(rows)} filas, {info['counts']['new_in_dev']} nuevos, {info['counts']['modified_in_dev']} modificados"

    # -- operaciones de copia (Etapa 2) --------------------------------
    def repos_map(self) -> dict[str, str]:
        m = dict(self.meta)
        return {"principal": m.get("principal", ""), "addons": m.get("addons", "")}

    def prepare(self):
        """Re-verifica la selección y genera la vista previa.
        Nunca ejecuta copias."""
        from .copy_engine import build_operations

        self.ops = build_operations(
            self.rows, set(self.selection), self.meta.get("dev", ""),
            self.repos_map(), self.snapshot,
        )
        self.pending = True
        self.results = []
        return self.ops

    def authorize_and_execute(self):
        """Segunda acción explícita: ejecuta solo lo autorizado."""
        from .copy_engine import execute_operations

        if not self.pending:
            return []
        self.results = execute_operations(self.ops, authorized=True)
        self.pending = False
        return self.results

    def op_status(self, row) -> str:
        op = next((o for o in self.ops if o.path == row.path and o.destination == row.destination), None)
        if op is not None:
            return {"copiable": "P(copiable)", "bloqueada": "B(bloqueada)",
                    "identica": "=(idéntico)"}.get(op.status, op.status)
        got = next((r for r in self.results if r["path"] == row.path), None)
        if got is not None:
            return f"✓({got['status']})"
        if (row.destination, row.path) in self.selection:
            return "seleccionado"
        return ""

    def summary(self) -> str:
        n = len(self.selection)
        return f"{n} archivo(s) seleccionado(s) — sin operaciones, solo memoria"

    def detail(self, row, absolute_root: dict[str, str]) -> str:
        lines = [
            f"Ruta: {row.path}",
            f"Dueño: {row.owner}",
            f"Destino: {row.destination}",
            f"Eje A (Dev↔repo): {row.axis_a}",
            f"Eje B (Git): {row.axis_b}",
        ]
        mark = markers(row)
        if mark:
            lines.append(f"Marcador: {mark}")
        detail_text = state_detail(row)
        if detail_text:
            lines.append(f"Detalle: {detail_text}")
        if getattr(row, "perm", ""):
            lines.append(f"Permisos Dev→repo: {row.perm}")
        dev_path = os.path.join(absolute_root.get("dev", ""), row.path)
        repo_path = ""
        dest = absolute_root.get(row.destination, "")
        if dest:
            repo_path = os.path.join(dest, row.path)
        for label, path in (("Dev", dev_path), ("Repo", repo_path)):
            if path and os.path.lexists(path):
                st = os.lstat(path)
                kind = "symlink" if os.path.islink(path) else "file"
                mode = oct(st.st_mode & 0o777)
                executable = " ejecutable" if st.st_mode & 0o111 else ""
                lines.append(f"{label}: {kind} size={st.st_size} mode={mode}{executable}")
                if kind == "symlink":
                    lines.append(f"  -> {os.readlink(path)}")
        if row.incidences:
            lines.append(f"Incidencias: {', '.join(row.incidences)}")
        for extra in row.extra:
            lines.append(f"  {extra}")
        if dev_path and repo_path and os.path.exists(dev_path) and os.path.exists(repo_path):
            diff = make_diff(dev_path, repo_path)
            if diff is None:
                lines.append("(binario o symlink: sin diff textual — ver metadatos)")
            else:
                lines.append(f"--- diff Dev vs repositorio ({len(diff)} líneas) ---")
                lines.extend(diff)
        return "\n".join(lines)

    def render_list(self) -> str:
        visible = self.visible()
        if visible:
            self.cursor = max(0, min(self.cursor, len(visible) - 1))
        filter_label = dict(FILTERS)[self.filter_key]
        output = [
            f"=== Gipler TUI (vista: {self.tab} · filtro: {filter_label}) ===",
            f"filas visibles: {len(visible)} · selección: {self.summary()}",
        ]
        for warning in self.warnings:
            output.append(f"AVISO: {warning}")
        last_dir = None
        for index, row in enumerate(visible):
            directory = os.path.dirname(row.path) or "."
            if directory != last_dir:
                output.append(f"[{directory}/]")
                last_dir = directory
            marker = ">>" if index == self.cursor else "  "
            selected = "[x]" if (row.destination, row.path) in self.selection else "[ ]"
            tag = self.op_status(row)
            glyphs = markers(row)
            detail_text = state_detail(row)
            output.append(
                f"{marker} {selected} {row.path}{' ' + glyphs if glyphs else ''} | "
                f"{row.owner} -> {row.destination} | A={row.axis_a} B={row.axis_b}"
                + (f" · {detail_text}" if detail_text else "")
                + (f" †{','.join(row.incidences)}" if row.incidences else "")
                + (f" [{tag}]" if tag else "")
            )
        if self.ops:
            from .copy_engine import preview

            output.append(preview(self.ops))
        if self.results:
            output.append("--- resultado individual ---")
            for result in self.results:
                output.append(
                    f"  {result['path']}: {result['status']}"
                    + (f" ({result.get('detail', '')})" if result.get("detail") else "")
                )
        return "\n".join(output)

    def render_detail(self) -> str:
        row = self.current()
        if row is None:
            return "(sin selección)"
        return self.detail(row, self.meta)


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
        self.selection: set[tuple[str, str]] = set()
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
        destination_id = entry.eligible_destination_source_id
        if destination_id is None:
            return
        key = destination_id, entry.path
        if key not in self.eligible_keys:
            return
        if key in self.selection:
            self.selection.remove(key)
        else:
            self.selection.add(key)
        self.ops = []
        self.pending = False

    def select_safe_visible(self) -> None:
        from .copy_engine import build_operations

        visible_keys = set()
        for entry in self.visible():
            destination_id = getattr(entry, "eligible_destination_source_id", None)
            if destination_id is not None:
                visible_keys.add((destination_id, entry.path))
        rows = [
            row for row in self.analysis.copy_rows()
            if (row.destination, row.path) in visible_keys
        ]
        keys = {(row.destination, row.path) for row in rows}
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
        keys = {(row.destination, row.path) for row in rows}
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
            key = None
            physical = getattr(entry, "physical", entry)
            if hasattr(entry, "eligible_destination_source_id"):
                destination_id = entry.eligible_destination_source_id
                if destination_id is not None:
                    key = (destination_id, entry.path)
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


def run_curses(state: State) -> bool:
    """Bucle curses real. Devuelve False si no hay terminal disponible."""
    try:
        import curses
    except ImportError:
        return False
    if not os.isatty(1):
        return False

    def main(stdscr):
        curses.curs_set(0)
        tab_idx = 0
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            mid = max(10, h // 2)
            for y, line in enumerate(state.render_list().splitlines()[:mid]):
                try:
                    stdscr.addnstr(y, 0, line, w - 1)
                except Exception:
                    pass
            detail = state.render_detail()
            for y, line in enumerate(detail.splitlines()[: max(0, h - mid - 3)]):
                try:
                    stdscr.addnstr(mid + y, 0, line, w - 1)
                except Exception:
                    pass
            hints = (
                "↑↓ nav · 1/2/3 pestaña · f filtro · espacio marcar · "
                "s selección segura · p preparar · e autorizar+ejecutar · r reanalizar · c limpiar · q salir"
            )
            try:
                stdscr.addnstr(h - 1, 0, hints, w - 1)
            except Exception:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            if ch == curses.KEY_UP:
                state.move(-1)
            elif ch == curses.KEY_DOWN:
                state.move(1)
            elif ch in (ord("1"), ord("2"), ord("3")):
                state.tab = TABS[int(chr(ch)) - 1]
                state.cursor = 0
            elif ch in (ord("f"), ord("F")):
                idx = [k for k, _ in FILTERS].index(state.filter_key)
                state.filter_key = FILTERS[(idx + 1) % len(FILTERS)][0]
                state.cursor = 0
            elif ch == ord(" "):
                state.toggle()
            elif ch in (ord("s"), ord("S")):
                state.select_safe_visible()
            elif ch in (ord("p"), ord("P")):
                state.prepare()
            elif ch in (ord("e"), ord("E")):
                state.authorize_and_execute()
            elif ch in (ord("r"), ord("R")):
                msg = state.refresh()
                if msg:
                    state.warnings = list(state.warnings) + [msg]
            elif ch in (ord("c"), ord("C")):
                state.clear()

    curses.wrapper(main)
    return True


def make_state(dev: str, principal: str, addons: str) -> State:
    _, rows, info = analyze(dev, principal, addons)
    return State(rows, info["meta"], info["warnings"], snapshot=info.get("snapshot"))


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
    p.add_argument("--profile", default="", help="Usar el ID de un perfil persistido")
    p.add_argument("--dev", default=None)
    p.add_argument("--principal", default=None)
    p.add_argument("--addons", default=None)
    args = p.parse_args(argv)
    if args.profile:
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
    if args.dev and args.principal and args.addons:
        state = make_state(args.dev, args.principal, args.addons)
    else:
        from .config import configured_paths

        default_dev, default_principal, default_addons = configured_paths()
        state = make_state(
            args.dev or default_dev,
            args.principal or default_principal,
            args.addons or default_addons,
        )
    if args.demo:
        for tab in TABS:
            state.tab = tab
            print(state.render_list())
            print(state.render_detail())
            print()
        return 0
    if not run_curses(state):
        print("Sin terminal interactiva. Use --demo para inspeccionar.")
        print(state.render_list())
        print(state.render_detail())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
