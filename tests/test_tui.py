"""Tests de la TUI de perfiles (lógica de estado, sin terminal)."""
import os
import tempfile
import unittest

from gipler.profile_analysis import analyze_profile
from gipler.tui import ProfileState
from .helpers import make_profile, write


class ProfileTuiStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile, self.work, self.roots = make_profile(
            self.tmp.name,
            work_files={"new.txt": "new\n", "local.txt": "same\n"},
            sources=[{"name": "Ref", "files": {"local.txt": "same\n"}}],
            assignments={"new.txt": "src_000000"},
        )
        write(os.path.join(self.roots["src_000000"], "local.txt"), "local\n")
        self.analysis = analyze_profile(self.profile)
        self.state = ProfileState(self.profile, self.analysis)

    def tearDown(self):
        self.profile.view["active_tab"] = "inicio"

    def test_views_and_navigation(self):
        self.assertEqual(
            self.state.views,
            ["inicio", "source:src_000000", "excluidos", "indeterminados"],
        )
        self.state.active_view = "source:src_000000"
        rows = self.state.visible()
        self.assertTrue(rows)
        n = len(rows)
        self.state.move(n)
        self.assertEqual(self.state.cursor, 0)
        self.state.move(-1)
        self.assertEqual(self.state.cursor, n - 1)

    def test_selection_toggle(self):
        self.state.active_view = "source:src_000000"
        self.state.cursor = 0
        entry = self.state.current()
        destination = entry.eligible_destination_source_id
        if destination is None:
            self.skipTest("sin destino elegible")
        self.state.toggle()
        self.assertIn((destination, entry.path), self.state.selection)
        self.state.toggle()
        self.assertNotIn((destination, entry.path), self.state.selection)

    def test_safe_selection_excludes_local(self):
        self.state.active_view = "source:src_000000"
        self.state.select_safe_visible()
        for entry in self.state.visible():
            if entry.path == "local.txt":
                destination = entry.eligible_destination_source_id
                if destination is not None:
                    self.assertNotIn((destination, entry.path), self.state.selection)

    def test_detail_text(self):
        self.state.active_view = "source:src_000000"
        entry = self.state.current()
        detail = self.state.render_profile_detail()
        self.assertIn(entry.path, detail)


if __name__ == "__main__":
    unittest.main()
