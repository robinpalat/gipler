"""Tests Fase 1 GUI (offscreen, sin copias reales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication, QSplitter, QTabWidget

from gipler.gui.main_window import GiplerWindow
from gipler.gui.models.comparison_model import ComparisonModel
from gipler.gui.models.filter_model import FilterModel
from gipler.gui.inspector import Inspector
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class Phase1Tests(unittest.TestCase):
    def test_window_structure(self):
        w = GiplerWindow()
        self.assertEqual(w.repo_names(), ["principal", "addons", "sin determinar"])
        self.assertIsInstance(w.splitter, QSplitter)
        self.assertIsInstance(w.bottom_splitter, QSplitter) if hasattr(w, "bottom_splitter") else None
        self.assertFalse(hasattr(w, "inspector"))
        w.close()

    def test_model_and_proxy_filters(self):
        from gipler.gui.models.filter_model import visible_file_count
        m = ComparisonModel([
            _row("a.sh", "modified_in_dev", "tracked_clean"),
            _row("b.png", "identical", "tracked_clean"),
            _row("c.txt", "modified_in_dev", "tracked_modified", inc=["x"]),
        ])
        self.assertEqual(m.rowCount(), 3)
        self.assertEqual(m.data(m.index(0, 0)), "a.sh")
        proxy = FilterModel()
        proxy.setSourceModel(m)
        # List-model legacy path: sin nodos-árbol, rowCount visible.
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
        m = ComparisonModel([_row("x", "new_in_dev", "ignored")])
        r = m.row(0)
        self.assertEqual(r.axis_a, "new_in_dev")
        self.assertEqual(r.axis_b, "ignored")


if __name__ == "__main__":
    unittest.main()
