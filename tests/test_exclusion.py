"""Tests de exclusión (HOME temporal; sin tocar Dev/repos reales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler import ignore
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class ExclusionTests(unittest.TestCase):
    def setUp(self):
        self._orig_home = os.environ.get("HOME")
        self.tmp_home = tempfile.mkdtemp()
        os.environ["HOME"] = self.tmp_home
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.repo = os.path.join(root, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)
        for name in ("a.txt", "d/b.txt", "keep.txt"):
            os.makedirs(os.path.dirname(os.path.join(self.dev, name)), exist_ok=True)
        self.rows = [
            _row("a.txt", "new_in_dev", "untracked"),
            _row("d/b.txt", "new_in_dev", "untracked"),
            _row("keep.txt", "identical", "tracked_clean"),
        ]
        for name in ("a.txt", "d/b.txt", "keep.txt"):
            with open(os.path.join(self.dev, name), "w") as f:
                f.write(name)
        with open(os.path.join(self.repo, "keep.txt"), "w") as f:
            f.write("keep.txt")
        self.w = None

    def tearDown(self):
        if self.w:
            try:
                self.w.close()
            except Exception:
                pass
        self.tmp.cleanup()
        shutil.rmtree(self.tmp_home, ignore_errors=True)
        if self._orig_home:
            os.environ["HOME"] = self._orig_home

    def _window(self):
        self.w = GiplerWindow(
            rows=self.rows,
            meta={"dev": self.dev, "principal": self.repo, "addons": self.repo},
            snapshot={"dev": {}, "repos": {}},
        )
        return self.w

    def test_ignore_persists_and_filters(self):
        self.assertEqual(ignore.load_patterns(), [])
        ignore.add_pattern("a.txt")
        self.assertIn("a.txt", ignore.load_patterns())
        from gipler.analysis import analyze
        _, rows2, _ = analyze(self.dev, self.repo, self.repo)
        paths = [r.path for r in rows2]
        self.assertNotIn("a.txt", paths)
        self.assertIn("keep.txt", paths)

    def test_dir_recursive_exclusion(self):
        ignore.add_pattern("d/")
        from gipler.ignore import is_excluded
        self.assertTrue(is_excluded("d/b.txt", ["d/"]))

    def test_context_menu_exists(self):
        w = self._window()
        for panel in (w.dev_panel, w.dest_panel):
            self.assertIsNotNone(panel.tree.customContextMenuRequested)
            idx = w.proxy.index(0, 0) if panel is w.dev_panel else w.repo_proxy.index(0, 0)
            self.assertTrue(idx.isValid())

    def test_startup_inicio_checked(self):
        w = self._window()
        self.assertTrue(w.nav_buttons["inicio"].isChecked())
        for b in w.repo_buttons.values():
            self.assertFalse(b.isChecked())
        self.assertEqual(w.stacked.currentWidget(), w.inicio_panel)

    def test_reanalyze_updates_inicio(self):
        w = self._window()
        w.reanalyze()
        self.assertIn("keep.txt", [r.path for r in w.rows])

    def test_exclusion_does_not_write(self):
        before_dev = {f: os.path.getsize(os.path.join(self.dev, f)) for f in ("a.txt", "d/b.txt", "keep.txt")}
        ignore.add_pattern("a.txt")
        ignore.add_pattern("d/")
        from gipler.analysis import analyze
        analyze(self.dev, self.repo, self.repo)
        after_dev = {f: os.path.getsize(os.path.join(self.dev, f)) for f in ("a.txt", "d/b.txt", "keep.txt")}
        self.assertEqual(before_dev, after_dev)
        self.assertFalse(os.path.exists(os.path.join(self.dev, ".gitignore")))


if __name__ == "__main__":
    unittest.main()
