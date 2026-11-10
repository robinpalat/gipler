"""Tests Fase 3 GUI (offscreen, sin copias reales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.repo = os.path.join(root, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)
        self.rows = [
            _row("a.txt", "identical", "tracked_clean"),
            _row("b.sh", "modified_in_dev", "tracked_clean"),
            _row("bin.dat", "modified_in_dev", "tracked_clean"),
            _row("empty.txt", "new_in_dev", "untracked"),
        ]
        def write(p, data):
            with open(p, "wb") as f:
                f.write(data if isinstance(data, bytes) else data.encode())
        write(os.path.join(self.dev, "a.txt"), "same\n")
        write(os.path.join(self.repo, "a.txt"), "same\n")
        write(os.path.join(self.dev, "b.sh"), "line1\nNEW\nline3\n")
        write(os.path.join(self.repo, "b.sh"), "line1\nOLD\nline3\n")
        write(os.path.join(self.dev, "bin.dat"), b"\x00\x01\xff")
        write(os.path.join(self.repo, "bin.dat"), b"\x00\x02\xff")
        write(os.path.join(self.dev, "empty.txt"), "")
        self.w = None

    def tearDown(self):
        if self.w:
            self.w.close()
        self.tmp.cleanup()

    def _win(self):
        self.w = GiplerWindow(rows=self.rows, meta={"dev": self.dev, "principal": self.repo, "addons": self.repo})
        return self.w

    def test_no_inspector_tabs(self):
        w = self._win()
        self.assertFalse(hasattr(w, "inspector"))
        self.assertTrue(hasattr(w, "inicio_panel"))

    def test_selection_updates_inicio_info(self):
        from PySide6.QtCore import QItemSelectionModel
        w = self._win()
        w.tree_model.set_rows(self.rows, "principal")
        idx = w.proxy.index(0, 0)
        w.dev_panel.tree.selectionModel().setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.Current)
        w.dev_panel.tree.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.Select)
        txt = w.inicio_panel.file_info.text()
        self.assertIn("a.txt", txt)

    def test_comparison_window_cases(self):
        from gipler.gui.comparison_window import ComparisonWindow
        w = ComparisonWindow(self.rows[1], self.dev, self.repo)
        texts = [w.diff.left.item(r).text() if w.diff.left.item(r) else "" for r in range(w.diff.row_count())]
        self.assertIn("NEW", " ".join(texts))
        w.close()
        w2 = ComparisonWindow(self.rows[2], self.dev, self.repo)
        self.assertIn("binario", w2.diff.left.item(0).text())
        w2.close()


if __name__ == "__main__":
    unittest.main()
