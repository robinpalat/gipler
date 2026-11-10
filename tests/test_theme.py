"""Tests de temas (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui import theme as th
from gipler.gui.main_window import GiplerWindow
from gipler.gui.models.comparison_tree import color_for_row
from gipler.report import Row

app = QApplication.instance() or QApplication([])


class ThemeTests(unittest.TestCase):
    def test_palettes(self):
        self.assertEqual(th.PALETTES["oscuro"]["fondo"], "#20252D")
        self.assertEqual(th.PALETTES["claro"]["fondo"], "#E9EDF2")
        self.assertEqual(th.PALETTES["oscuro"]["acento"], "#6BA6E8")

    def test_dynamic_apply_no_restart(self):
        th.apply_theme("oscuro")
        self.assertEqual(th.load_preference(), "oscuro")
        th.apply_theme("claro")
        self.assertEqual(th.load_preference(), "claro")
        th.save_preference("oscuro")

    def test_semantic_recognizable_both_themes(self):
        r = Row("x.txt", "núcleo", "principal", "new_in_dev", "untracked", [])
        self.assertEqual(color_for_row(r, "oscuro"), th.semantic("oscuro", "new_in_dev"))
        self.assertEqual(color_for_row(r, "claro"), th.semantic("claro", "new_in_dev"))

    def test_apply_preserves_window_state(self):
        w = GiplerWindow(rows=[], meta={})
        w.apply_theme("claro")
        w.apply_theme("oscuro")
        self.assertEqual(w.tree_model.semantic_theme, "oscuro")
        w.close()


if __name__ == "__main__":
    unittest.main()
