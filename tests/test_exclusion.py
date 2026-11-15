"""Tests de exclusión de perfiles (HOME temporal; sin tocar Dev/repos reales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from .helpers import make_profile

app = QApplication.instance() or QApplication([])


class ExclusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile, self.work, self.roots = make_profile(
            self.tmp.name,
            work_files={"a.txt": "a", "d/b.txt": "b", "keep.txt": "keep"},
            sources=[{"name": "Ref", "files": {"keep.txt": "keep"}}],
        )
        self.w = None

    def tearDown(self):
        if self.w:
            try:
                self.w.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def test_profile_exclusion_persists_and_filters(self):
        from gipler.profile import add_exclusion, load_profile
        from gipler.profile_analysis import analyze_profile

        add_exclusion(self.profile.id, "a.txt")
        self.assertIn("a.txt", load_profile(self.profile.id).exclusions)
        analysis = analyze_profile(load_profile(self.profile.id))
        paths = {entry.path for entry in analysis.entries}
        self.assertNotIn("a.txt", paths)
        self.assertIn("keep.txt", paths)

    def test_dir_recursive_exclusion(self):
        from gipler.ignore import is_excluded
        self.assertTrue(is_excluded("d/b.txt", ["d/"]))

    def test_context_menu_exists(self):
        self.w = GiplerWindow(profile=self.profile)
        for proxy in (self.w.proxy, self.w.repo_proxy):
            proxy.set_criteria(
                axis_a=None, axis_b=None, incidences=False, search="",
                owner="", exclude_identical=False,
            )
        for panel in (self.w.dev_panel, self.w.dest_panel):
            self.assertIsNotNone(panel.tree.customContextMenuRequested)
            idx = self.w.proxy.index(0, 0) if panel is self.w.dev_panel else self.w.repo_proxy.index(0, 0)
            self.assertTrue(idx.isValid())

    def test_startup_inicio_checked(self):
        self.w = GiplerWindow(profile=self.profile)
        self.assertTrue(self.w.nav_buttons["inicio"].isChecked())
        for b in self.w.repo_buttons.values():
            self.assertFalse(b.isChecked())
        self.assertEqual(self.w.stacked.currentWidget(), self.w.inicio_panel)

    def test_reanalyze_updates_inicio(self):
        self.w = GiplerWindow(profile=self.profile)
        self.w.reanalyze()
        self.assertIn("keep.txt", [r.path for r in self.w.rows])

    def test_exclusion_does_not_write(self):
        before_dev = {
            name: os.path.getsize(os.path.join(self.work, name))
            for name in ("a.txt", "d/b.txt", "keep.txt")
        }
        from gipler.profile import add_exclusion
        from gipler.profile_analysis import analyze_profile
        from gipler.profile import load_profile

        add_exclusion(self.profile.id, "a.txt")
        add_exclusion(self.profile.id, "d/")
        analyze_profile(load_profile(self.profile.id))
        after_dev = {
            name: os.path.getsize(os.path.join(self.work, name))
            for name in ("a.txt", "d/b.txt", "keep.txt")
        }
        self.assertEqual(before_dev, after_dev)
        self.assertFalse(os.path.exists(os.path.join(self.work, ".gitignore")))


if __name__ == "__main__":
    unittest.main()
