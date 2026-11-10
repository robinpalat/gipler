"""Desglose Git (contenido/permisos, staged/unstaged), `*`, `⌀` y `not_comparable`.

Cubre el motor (scanner, comparator, report, analysis), la representación
en GUI/TUI y la integración de escritorio (icono + `.desktop`).
"""
from __future__ import annotations

import os
import tempfile
import unittest

from .helpers import commit_all, git, make_repo, write

from gipler.comparator import compare_pair
from gipler.report import Row, markers, render, state_detail, tooltip_text
from gipler.scanner import Entry, git_change_details, scan_tree


def _row(path="a.sh", a="identical", b="tracked_clean", **kw):
    return Row(path, "núcleo", "principal", a, b, [], **kw)


# ---------------------------------------------------------------- motor
class MarkerSemanticsTests(unittest.TestCase):
    def test_asterisk_requires_identical_and_tracked_modified(self):
        self.assertTrue(_row(a="identical", b="tracked_modified").asterisk)
        # No es «pendiente de commit»: azul con Git limpio no lleva `*`.
        self.assertFalse(_row(a="modified_in_dev", b="tracked_modified").asterisk)
        self.assertFalse(_row(a="identical", b="tracked_clean").asterisk)

    def test_perm_marker_is_orthogonal_to_axis_a(self):
        r = _row(a="identical", perm="755→644 · bit ejecutable")
        self.assertTrue(r.perm_marker)
        self.assertEqual(r.axis_a, "identical")
        self.assertFalse(r.asterisk)
        self.assertFalse(_row().perm_marker)

    def test_markers_composition(self):
        r = _row(a="identical", b="tracked_modified", perm="644→755")
        self.assertEqual(markers(r), "*⌀")
        self.assertEqual(markers(_row()), "")

    def test_state_detail_empty_without_detail(self):
        self.assertEqual(state_detail(_row()), "")
        self.assertEqual(
            state_detail(_row(git_change="contenido", git_stage="staged")),
            "contenido · staged",
        )
        self.assertEqual(
            state_detail(_row(perm="755→644 · bit ejecutable")),
            "⌀ 755→644 · bit ejecutable",
        )

    def test_tooltip_carries_markers_and_detail(self):
        r = _row(a="identical", b="tracked_modified",
                 git_change="contenido", git_stage="unstaged", perm="755→644")
        text = tooltip_text(r)
        self.assertIn("Marcador: *⌀", text)
        self.assertIn("Detalle: contenido · unstaged · ⌀ 755→644", text)

    def test_report_sections_4b_and_4c(self):
        rows = [
            _row("nc.sh", a="not_comparable"),
            _row("p.sh", perm="755→644"),
        ]
        out = render({"dev": "d", "principal": "p", "addons": "a"}, rows, [])
        self.assertIn("## 4b. No comparables (not_comparable) (1)", out)
        self.assertIn("## 4c. Diferencia de permisos Dev→repo (⌀) (1)", out)
        self.assertIn("[*]", render({}, [_row(b="tracked_modified", a="identical")], []))


class NotComparableTests(unittest.TestCase):
    def test_missing_hash_never_infers_modification(self):
        dev = Entry(path="x", exists=True)
        repo = Entry(path="x", exists=True)
        self.assertEqual(compare_pair(dev, repo), "not_comparable")

    def test_same_hash_still_identical(self):
        dev = Entry(path="x", exists=True, sha256="a" * 64)
        repo = Entry(path="x", exists=True, sha256="a" * 64)
        self.assertEqual(compare_pair(dev, repo), "identical")

    def test_absence_keeps_its_own_states(self):
        self.assertEqual(
            compare_pair(None, Entry(path="x", exists=True)), "missing_in_dev"
        )
        self.assertEqual(
            compare_pair(Entry(path="x", exists=True), None), "new_in_dev"
        )

    def test_end_to_end_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev = os.path.join(tmp, "dev")
            principal = make_repo(tmp, "principal")
            addons = make_repo(tmp, "addons")
            os.makedirs(dev, exist_ok=True)
            write(os.path.join(dev, "main.sh"), "same\n", executable=True)
            write(os.path.join(principal, "main.sh"), "same\n", executable=True)
            commit_all(principal)
            os.chmod(os.path.join(dev, "main.sh"), 0o000)
            from gipler.analysis import analyze

            _, rows, info = analyze(dev, principal, addons)
            target = [r for r in rows if r.path == "main.sh"]
            self.assertTrue(target, "la fila debe existir")
            self.assertEqual(target[0].axis_a, "not_comparable")
            self.assertEqual(info["counts"]["not_comparable"], 1)


class GitChangeDetailsTests(unittest.TestCase):
    def _repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = make_repo(tmp.name, "repo")
        write(os.path.join(repo, "a.sh"), "v1\n")
        write(os.path.join(repo, "mode.sh"), "x\n", executable=True)
        commit_all(repo)
        return repo

    def test_unstaged_content(self):
        repo = self._repo()
        write(os.path.join(repo, "a.sh"), "v2\n")
        self.assertEqual(git_change_details(repo), {"a.sh": ("contenido", "unstaged")})

    def test_staged_content(self):
        repo = self._repo()
        write(os.path.join(repo, "a.sh"), "v2\n")
        git(repo, "add", "a.sh")
        self.assertEqual(git_change_details(repo), {"a.sh": ("contenido", "staged")})

    def test_staged_and_unstaged(self):
        repo = self._repo()
        write(os.path.join(repo, "a.sh"), "v2\n")
        git(repo, "add", "a.sh")
        write(os.path.join(repo, "a.sh"), "v3\n")
        self.assertEqual(
            git_change_details(repo), {"a.sh": ("contenido", "staged+unstaged")}
        )

    def test_mode_only_is_permissions_not_content(self):
        repo = self._repo()
        os.chmod(os.path.join(repo, "mode.sh"), 0o644)
        details = git_change_details(repo)
        self.assertEqual(details, {"mode.sh": ("permisos", "unstaged")})

    def test_scan_tree_attaches_details(self):
        repo = self._repo()
        write(os.path.join(repo, "a.sh"), "v2\n")
        entries = scan_tree(repo, git=True)
        self.assertEqual(entries["a.sh"].git_change, "contenido")
        self.assertEqual(entries["a.sh"].git_stage, "unstaged")
        self.assertEqual(entries["a.sh"].git_state, "tracked_modified")
        self.assertEqual(entries["mode.sh"].git_change, "")


class AnalysisPermisosTests(unittest.TestCase):
    def test_perm_diff_does_not_touch_axis_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev = os.path.join(tmp, "dev")
            principal = make_repo(tmp, "principal")
            addons = make_repo(tmp, "addons")
            os.makedirs(dev, exist_ok=True)
            write(os.path.join(dev, "main.sh"), "same\n", executable=True)
            repo_file = os.path.join(principal, "main.sh")
            write(repo_file, "same\n")
            os.chmod(repo_file, 0o644)
            commit_all(principal)
            from gipler.analysis import analyze

            _, rows, info = analyze(dev, principal, addons)
            target = next(r for r in rows if r.path == "main.sh")
            self.assertEqual(target.axis_a, "identical")
            self.assertEqual(target.axis_b, "tracked_clean")
            self.assertEqual(target.perm, "755→644 · bit ejecutable")
            self.assertTrue(target.perm_marker)
            self.assertEqual(info["counts"]["perm_diff"], 1)
            self.assertEqual(info["counts"]["git_change_content"], 0)

    def test_asterisk_end_to_end_with_pending_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev = os.path.join(tmp, "dev")
            principal = make_repo(tmp, "principal")
            addons = make_repo(tmp, "addons")
            os.makedirs(dev, exist_ok=True)
            write(os.path.join(principal, "main.sh"), "v1\n")
            commit_all(principal)
            # Repo con cambio sin staged; Dev ya refleja el nuevo contenido.
            write(os.path.join(principal, "main.sh"), "v2\n")
            write(os.path.join(dev, "main.sh"), "v2\n")
            from gipler.analysis import analyze

            _, rows, info = analyze(dev, principal, addons)
            target = next(r for r in rows if r.path == "main.sh")
            self.assertEqual(target.axis_a, "identical")
            self.assertEqual(target.axis_b, "tracked_modified")
            self.assertTrue(target.asterisk)
            self.assertEqual(target.git_change, "contenido")
            self.assertEqual(target.git_stage, "unstaged")
            self.assertEqual(info["counts"]["git_change_content"], 1)
            self.assertEqual(info["counts"]["git_staged"], 0)


# ---------------------------------------------------------------- GUI
class GuiMarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _window(self, rows):
        from gipler.gui.main_window import GiplerWindow

        w = GiplerWindow(rows=rows)
        self.addCleanup(w.close)
        return w

    def _index(self, w, path):
        from PySide6.QtCore import QModelIndex

        found = []

        def walk(proxy, parent=QModelIndex()):
            for i in range(proxy.rowCount(parent)):
                idx = proxy.index(i, 0, parent)
                node = w.tree_model.node_at(proxy.mapToSource(idx))
                if node.path == path:
                    found.append(idx)
                    return True
                if walk(proxy, idx):
                    return True
            return False

        walk(w.proxy)
        return found[0]

    def test_tree_column_zero_shows_markers(self):
        rows = [
            _row("star.sh", a="identical", b="tracked_modified"),
            _row("perm.sh", a="identical", perm="755→644"),
            _row("plain.sh", a="modified_in_dev", b="tracked_clean"),
        ]
        w = self._window(rows)
        for path, expected in (
            ("star.sh", "star.sh *"),
            ("perm.sh", "perm.sh ⌀"),
            ("plain.sh", "plain.sh"),
        ):
            idx = self._index(w, path)
            self.assertEqual(w.proxy.data(idx), expected)

    def test_tree_column_one_keeps_axis_b_and_appends_detail(self):
        rows = [
            _row("plain.sh", a="modified_in_dev", b="tracked_clean"),
            _row("det.sh", a="identical", b="tracked_modified",
                 git_change="contenido", git_stage="staged"),
        ]
        w = self._window(rows)
        self.assertEqual(
            w.proxy.data(self._index(w, "plain.sh").siblingAtColumn(1)),
            "tracked_clean",
        )
        self.assertEqual(
            w.proxy.data(self._index(w, "det.sh").siblingAtColumn(1)),
            "tracked_modified · contenido · staged",
        )

    def test_tooltip_exposes_markers(self):
        rows = [_row("star.sh", a="identical", b="tracked_modified",
                     git_change="contenido", git_stage="unstaged")]
        w = self._window(rows)
        from PySide6.QtCore import Qt

        text = w.proxy.data(self._index(w, "star.sh"), role=Qt.ToolTipRole)
        self.assertIn("Marcador: *", text)
        self.assertIn("contenido · unstaged", text)

    def test_not_comparable_filter_and_color(self):
        from gipler.gui.main_window import AXIS_A
        from gipler.gui.models.comparison_tree import STATE_COLORS, color_for_row
        from gipler.gui.theme import semantic

        self.assertIn("not_comparable", AXIS_A)
        rows = [_row("nc.sh", a="not_comparable", b="tracked_clean")]
        w = self._window(rows)
        self.assertIn("not_comparable", [w.axis_a_box.itemText(i)
                                         for i in range(w.axis_a_box.count())])
        w.axis_a_box.setCurrentText("not_comparable")
        from gipler.gui.models.filter_model import visible_file_count

        self.assertEqual(visible_file_count(w.proxy), 1)
        color = color_for_row(rows[0], "oscuro")
        self.assertEqual(color, semantic("oscuro", "not_comparable"))
        self.assertNotEqual(color, semantic("oscuro", "modified_in_dev"))
        self.assertNotEqual(color, STATE_COLORS["modified_in_dev"])
        self.assertIn("not_comparable", STATE_COLORS)

    def test_legend_mentions_new_states_and_markers(self):
        from PySide6.QtWidgets import QLabel

        w = self._window([_row()])
        texts = {lbl.text() for lbl in w.findChildren(QLabel)}
        self.assertTrue(any("No comparable" in t for t in texts))
        self.assertTrue(any("* sincronizado" in t for t in texts))
        self.assertTrue(any("⌀" in t for t in texts))

    def test_window_and_app_use_official_icon(self):
        from PySide6.QtWidgets import QApplication

        from gipler.gui.main_window import GiplerWindow, _app_icon
        from gipler.resources import master_icon

        self.assertTrue(os.path.isfile(master_icon()))
        self.assertEqual(_app_icon(), master_icon())
        w = self._window([_row()])
        self.assertFalse(w.windowIcon().isNull())
        self.assertEqual(QApplication.applicationName(), "Gipler")
        self.assertEqual(QApplication.desktopFileName(), "gipler")


# ---------------------------------------------------------------- TUI
class TuiMarkerTests(unittest.TestCase):
    def _state(self, rows):
        from gipler.tui import State

        return State(rows, {"dev": "", "principal": "", "addons": ""}, [])

    def test_filters_include_not_comparable_and_permisos(self):
        from gipler.tui import FILTERS

        keys = [k for k, _ in FILTERS]
        self.assertIn("not_comparable", keys)
        self.assertIn("permisos", keys)

        rows = [
            _row("nc.sh", a="not_comparable"),
            _row("p.sh", a="identical", perm="755→644"),
            _row("ok.sh", a="modified_in_dev"),
        ]
        st = self._state(rows)
        st.filter_key = "not_comparable"
        self.assertEqual([r.path for r in st.visible()], ["nc.sh"])
        st.filter_key = "permisos"
        self.assertEqual([r.path for r in st.visible()], ["p.sh"])

    def test_detail_and_render_list_show_markers(self):
        rows = [_row("star.sh", a="identical", b="tracked_modified",
                     git_change="contenido", git_stage="unstaged", perm="755→644")]
        st = self._state(rows)
        detail = st.detail(rows[0], {"dev": "", "principal": "", "addons": ""})
        self.assertIn("Marcador: *⌀", detail)
        self.assertIn("Detalle: contenido · unstaged · ⌀ 755→644", detail)
        listing = st.render_list()
        self.assertIn("star.sh *⌀", listing)
        self.assertIn("· contenido · unstaged · ⌀ 755→644", listing)


# ------------------------------------------------------- escritorio
class DesktopResourcesTests(unittest.TestCase):
    def test_packaged_assets_exist(self):
        from gipler import resources

        self.assertTrue(os.path.isfile(resources.master_icon()))
        self.assertTrue(os.path.isfile(resources.ico_path()))
        sizes = resources.available_sizes()
        for size in (16, 32, 48, 128, 256, 512):
            self.assertIn(size, sizes)
            self.assertTrue(os.path.isfile(resources.icon_path(size)))
        self.assertEqual(resources.icon_path(9999), resources.master_icon())

    def test_desktop_entry_content(self):
        from gipler import resources

        entry = resources.desktop_entry(exec_cmd="/opt/gipler/run-gipler")
        self.assertIn("[Desktop Entry]", entry)
        self.assertIn("Type=Application", entry)
        self.assertIn("Name=Gipler", entry)
        self.assertIn("Icon=gipler", entry)
        self.assertIn("Exec=/opt/gipler/run-gipler %F", entry)
        self.assertIn("StartupWMClass=Gipler", entry)
        self.assertNotIn("\n\n[", entry)

    def test_install_and_uninstall_roundtrip(self):
        from gipler import resources

        with tempfile.TemporaryDirectory() as tmp:
            data_home = os.path.join(tmp, "share")
            written = resources.install_desktop(
                exec_cmd="/opt/gipler/run-gipler", home=data_home
            )
            desktop = os.path.join(data_home, "applications", "gipler.desktop")
            self.assertIn(desktop, written)
            self.assertTrue(os.path.isfile(desktop))
            with open(desktop, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Icon=gipler", content)
            for size in resources.available_sizes():
                self.assertTrue(
                    os.path.isfile(
                        os.path.join(
                            data_home, "icons", "hicolor",
                            f"{size}x{size}", "apps", "gipler.png",
                        )
                    )
                )
            removed = resources.uninstall_desktop(home=data_home)
            self.assertIn(desktop, removed)
            self.assertFalse(os.path.isfile(desktop))


if __name__ == "__main__":
    unittest.main()
