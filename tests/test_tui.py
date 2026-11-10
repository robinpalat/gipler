"""Tests de la TUI (lógica de estado, sin terminal)."""
import os
import unittest

from gipler.tui import State, FILTERS
from .helpers import make_repo, write, commit_all, dev_fixture


def _state():
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    root = tmp.name
    dev = dev_fixture(root, {"Feeds": ("external", ["addons/Feeds/cnfg.sh", "addons/Feeds/mod.txt"], {})})
    principal = make_repo(root, "principal")
    addons = make_repo(root, "addons")
    write(os.path.join(principal, "main.sh"), "v1\n")
    write(os.path.join(addons, "addons/Feeds/cnfg.sh"), "x\n")
    write(os.path.join(addons, "addons/Feeds/mod.txt"), "old\n")
    commit_all(principal)
    commit_all(addons)
    write(os.path.join(dev, "main.sh"), "v2\n")
    write(os.path.join(dev, "addons/Feeds/mod.txt"), "new\n")
    from gipler.analysis import analyze
    _, rows, info = analyze(dev, principal, addons)
    return tmp, State(rows, info["meta"], info["warnings"])


class TuiStateTests(unittest.TestCase):
    def test_tabs_and_filters(self):
        tmp, st = _state()
        self.addCleanup(tmp.cleanup)
        st.tab = "principal"
        st.filter_key = "modified_in_dev"
        self.assertIn("main.sh", [r.path for r in st.visible()])
        st.filter_key = "todos"
        st.tab = "addons"
        paths = [r.path for r in st.visible()]
        self.assertIn("addons/Feeds/mod.txt", paths)

    def test_navigation_wrap_and_selection(self):
        tmp, st = _state()
        self.addCleanup(tmp.cleanup)
        st.tab = "addons"
        n = len(st.visible())
        st.move(n)
        self.assertEqual(st.cursor, 0)
        st.move(-1)
        self.assertEqual(st.cursor, n - 1)
        st.toggle()
        self.assertEqual(len(st.selection), 1)
        st.toggle()
        self.assertEqual(len(st.selection), 0)

    def test_safe_group_excludes_local_and_ambiguous(self):
        tmp, st = _state()
        self.addCleanup(tmp.cleanup)
        # Edición local en addons debe hacerse ANTES de analizar.
        import tempfile
        t2 = tempfile.TemporaryDirectory()
        self.addCleanup(t2.cleanup)
        dev = dev_fixture(t2.name, {"Feeds": ("external", ["addons/Feeds/cnfg.sh", "addons/Feeds/mod.txt"], {})})
        principal = make_repo(t2.name, "principal")
        addons = make_repo(t2.name, "addons")
        write(os.path.join(addons, "addons/Feeds/mod.txt"), "v1\n")
        write(os.path.join(addons, "addons/Feeds/cnfg.sh"), "x\n")
        commit_all(addons)
        write(os.path.join(addons, "addons/Feeds/mod.txt"), "local\n")
        from gipler.analysis import analyze
        _, rows, info = analyze(dev, principal, addons)
        st2 = State(rows, info["meta"], info["warnings"])
        st2.tab = "addons"
        st2.select_safe_visible()
        # mod.txt está tracked_modified -> excluido del grupo seguro.
        for r in st2.visible():
            if r.path == "addons/Feeds/mod.txt":
                self.assertNotIn((r.destination, r.path), st2.selection)
        st2.clear()
        self.assertEqual(len(st2.selection), 0)

    def test_detail_text_diff_and_binary_metadata(self):
        import tempfile

        tmp, st = _state()
        self.addCleanup(tmp.cleanup)
        st.tab = "principal"
        st.filter_key = "modified_in_dev"
        d = st.render_detail()
        self.assertIn("main.sh", d)
        self.assertIn("diff Dev vs repositorio", d)
        # Binario: metadatos, sin diff textual.
        t2 = tempfile.TemporaryDirectory()
        self.addCleanup(t2.cleanup)
        dev_b = os.path.join(t2.name, "dev")
        rep_b = os.path.join(t2.name, "rep")
        write(os.path.join(dev_b, "x.bin"), b"\x89PNG")
        write(os.path.join(rep_b, "x.bin"), b"\x89PNH")
        from gipler.report import Row as Row_
        row = Row_("x.bin", "núcleo", "addons", "modified_in_dev", "tracked_clean", [])
        st_b = State([row], {"dev": dev_b, "addons": rep_b}, [])
        txt = st_b.detail(row, {"dev": dev_b, "addons": rep_b})
        self.assertIn("size=", txt)
        self.assertIn("sin diff textual", txt)


if __name__ == "__main__":
    unittest.main()
