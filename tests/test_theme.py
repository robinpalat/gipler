"""Tests de temas (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from gipler.gui import styles
from gipler.gui import theme as th
from gipler.gui.models.comparison_tree import color_for_row
from gipler.gui.summary_panel import SummaryPanel
from gipler.report import Row
from .helpers import make_profile_window

app = QApplication.instance() or QApplication([])


class _MemorySettings:
    def __init__(self):
        self.values: dict[str, object] = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


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
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        w, patcher = make_profile_window(
            tmp.name, [], sources=[{"id": "src_0", "name": "Src"}]
        )
        self.addCleanup(patcher.stop)
        self.addCleanup(w.close)
        w.apply_theme("claro")
        w.apply_theme("oscuro")
        self.assertEqual(w.tree_model.semantic_theme, "oscuro")


class ThemePropagationTests(unittest.TestCase):
    """Alternar temas en runtime sin reiniciar ni tocar la configuración real."""

    def setUp(self):
        self.settings = _MemorySettings()
        self.patcher = patch(
            "gipler.config.get_settings", return_value=self.settings
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self._reset_applied_theme)
        th._APPLIED_THEME = None
        styles._APPLIED_THEME = None

    @staticmethod
    def _reset_applied_theme():
        th._APPLIED_THEME = None
        styles._APPLIED_THEME = None

    def _assert_stylesheet_uses(self, theme: str) -> None:
        sheet = app.styleSheet()
        current = th.PALETTES[theme]
        other = th.PALETTES["claro" if theme == "oscuro" else "oscuro"]
        self.assertIn(current["panel"], sheet)
        self.assertIn(current["acento"], sheet)
        self.assertNotIn(other["panel"], sheet)

    def test_switch_dark_light_dark_rebuilds_global_stylesheet(self):
        th.apply_theme("oscuro")
        self._assert_stylesheet_uses("oscuro")
        th.apply_theme("claro")
        self._assert_stylesheet_uses("claro")
        th.apply_theme("oscuro")
        self._assert_stylesheet_uses("oscuro")

    def test_summary_panel_follows_runtime_theme_switch(self):
        th.apply_theme("oscuro")
        panel = SummaryPanel()
        self.addCleanup(panel.close)
        panel.show()
        app.processEvents()
        self.assertEqual(panel._visual_theme, "oscuro")
        th.apply_theme("claro")
        app.processEvents()
        self.assertEqual(panel._visual_theme, "claro")
        self.assertIn(th.PALETTES["claro"]["panel2"], panel.styleSheet())
        self.assertNotIn(th.PALETTES["oscuro"]["panel2"], panel.styleSheet())
        th.apply_theme("oscuro")
        app.processEvents()
        self.assertEqual(panel._visual_theme, "oscuro")
        self.assertIn(th.PALETTES["oscuro"]["panel2"], panel.styleSheet())
        self.assertNotIn(th.PALETTES["claro"]["panel2"], panel.styleSheet())

    def test_preference_is_persisted_before_theme_is_applied(self):
        th.apply_theme("claro")
        self.assertEqual(self.settings.value("tema"), "claro")
        self.assertEqual(th.load_preference(), "claro")


if __name__ == "__main__":
    unittest.main()
