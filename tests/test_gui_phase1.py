"""Tests Fase 1 GUI (offscreen, sin copias reales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QSplitter

from gipler.gui.main_window import GiplerWindow
from gipler.gui.models.comparison_tree import ComparisonTreeModel
from gipler.gui.models.filter_model import FilterModel, visible_file_count
from gipler.report import Row
from .helpers import make_profile_window

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class Phase1Tests(unittest.TestCase):
    def test_window_structure(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        w, patcher = make_profile_window(
            tmp.name,
            [],
            sources=[{"id": "src_a", "name": "A"}, {"id": "src_b", "name": "B"}],
        )
        self.addCleanup(patcher.stop)
        self.addCleanup(w.close)
        self.assertEqual(w.repo_names(), ["src_a", "src_b"])
        self.assertIsInstance(w.splitter, QSplitter)
        self.assertFalse(hasattr(w, "inspector"))

    def test_model_and_proxy_filters(self):
        rows = [
            _row("a.sh", "modified_in_dev", "tracked_clean"),
            _row("b.png", "identical", "tracked_clean"),
            _row("c.txt", "modified_in_dev", "tracked_modified", inc=["x"]),
        ]
        m = ComparisonTreeModel(rows, "principal")
        self.assertEqual(len(m.file_nodes()), 3)
        proxy = FilterModel()
        proxy.setSourceModel(m)
        proxy.axis_a = "modified_in_dev"
        proxy.apply()
        self.assertEqual(visible_file_count(proxy), 2)
        proxy.axis_a = None
        proxy.only_incidences = True
        proxy.apply()
        self.assertEqual(visible_file_count(proxy), 1)
        proxy.only_incidences = False
        proxy.search = "b.png"
        proxy.apply()
        self.assertEqual(visible_file_count(proxy), 1)

    def test_model_two_axes_independent(self):
        m = ComparisonTreeModel([_row("x", "new_in_dev", "ignored")], "principal")
        node = m.file_nodes()[0]
        self.assertEqual(node.row.axis_a, "new_in_dev")
        self.assertEqual(node.row.axis_b, "ignored")


if __name__ == "__main__":
    unittest.main()
