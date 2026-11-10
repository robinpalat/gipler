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

TABS = ("principal", "addons", "sin determinar")

FILTERS = (
    ("todos", "Todos"),
    ("new_in_dev", "Nuevos en Dev"),
    ("modified_in_dev", "Modificados en Dev"),
    ("identical", "Idénticos"),
    ("tracked_modified", "Modificados localmente"),
    ("ignored", "Ignorados por Git"),
    ("missing_in_dev", "Ausentes en Dev"),
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

    # -- detalle ------------------------------------------------------
    def detail(self, row, absolute_root: dict[str, str]) -> str:
        lines = [
            f"Ruta: {row.path}",
            f"Dueño: {row.owner}",
            f"Destino: {row.destination}",
            f"Eje A (Dev↔repo): {row.axis_a}",
            f"Eje B (Git): {row.axis_b}",
        ]
        dev_path = os.path.join(absolute_root.get("dev", ""), row.path)
        repo_path = ""
        dest = absolute_root.get(row.destination, "")
        if dest:
            repo_path = os.path.join(dest, row.path)
        for label, p in (("Dev", dev_path), ("Repo", repo_path)):
            if p and os.path.lexists(p):
                st = os.lstat(p)
                kind = "symlink" if os.path.islink(p) else "file"
                mode = oct(st.st_mode & 0o777)
                exe = " ejecutable" if st.st_mode & 0o111 else ""
                lines.append(f"{label}: {kind} size={st.st_size} mode={mode}{exe}")
                if kind == "symlink":
                    lines.append(f"  -> {os.readlink(p)}")
        if row.incidences:
            lines.append(f"Incidencias: {', '.join(row.incidences)}")
        for e in row.extra:
            lines.append(f"  {e}")
        # Diff textual o metadatos binarios.
        if dev_path and repo_path and os.path.exists(dev_path) and os.path.exists(repo_path):
            d = make_diff(dev_path, repo_path)
            if d is None:
                lines.append("(binario o symlink: sin diff textual — ver metadatos)")
            else:
                lines.append(f"--- diff Dev vs repositorio ({len(d)} líneas) ---")
                lines.extend(d)
        return "\n".join(lines)

    # -- render plano (test/demo) --------------------------------------
    def render_list(self) -> str:
        vis = self.visible()
        if vis:
            self.cursor = max(0, min(self.cursor, len(vis) - 1))
        f_label = dict(FILTERS)[self.filter_key]
        out = [
            f"=== Gipler TUI (vista: {self.tab} · filtro: {f_label}) ===",
            f"filas visibles: {len(vis)} · selección: {self.summary()}",
        ]
        for w in self.warnings:
            out.append(f"AVISO: {w}")
        last_dir = None
        for i, r in enumerate(vis):
            d = os.path.dirname(r.path) or "."
            if d != last_dir:
                out.append(f"[{d}/]")
                last_dir = d
            mark = ">>" if i == self.cursor else "  "
            sel = "[x]" if (r.destination, r.path) in self.selection else "[ ]"
            tag = self.op_status(r)
            out.append(
                f"{mark} {sel} {r.path} | {r.owner} -> {r.destination} "
                f"| A={r.axis_a} B={r.axis_b}"
                + (f" †{','.join(r.incidences)}" if r.incidences else "")
                + (f" [{tag}]" if tag else "")
            )
        if self.ops:
            from .copy_engine import preview

            out.append(preview(self.ops))
        if self.results:
            out.append("--- resultado individual ---")
            for r in self.results:
                out.append(f"  {r['path']}: {r['status']}" + (f" ({r.get('detail', '')})" if r.get("detail") else ""))
        return "\n".join(out)

    def render_detail(self) -> str:
        r = self.current()
        if r is None:
            return "(sin selección)"
        return self.detail(r, self.meta)


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


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="gipler-tui")
    p.add_argument("--demo", action="store_true", help="Snapshot no interactivo")
    p.add_argument("--dev", default=None)
    p.add_argument("--principal", default=None)
    p.add_argument("--addons", default=None)
    args = p.parse_args(argv)
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
