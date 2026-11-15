"""Ajustes Fase 4 + codificación cromática (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.models.comparison_tree import (
    STATE_COLORS,
    color_for_row,
)
from gipler.report import Row
from .helpers import make_profile_window

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


ROWS = [
    _row("new.txt", "new_in_dev", "untracked"),
    _row("same.txt", "identical", "tracked_clean"),
]

SOURCES = [{"id": "principal", "name": "Principal"}, {"id": "addons", "name": "Addons"}]


class ColorTests(unittest.TestCase):
    def test_state_colors(self):
        from gipler.gui.models.comparison_tree import color_for_row
        from gipler.gui.theme import semantic
        cases = [
            (_row("n.txt", "new_in_dev", "untracked"), semantic("oscuro", "new_in_dev")),
            (_row("m.txt", "modified_in_dev", "tracked_clean"), semantic("oscuro", "modified_in_dev")),
            (_row("i.txt", "identical", "tracked_clean"), semantic("oscuro", "identical")),
            (_row("x.txt", "missing_in_dev", "tracked_clean"), semantic("oscuro", "missing_in_dev")),
        ]
        for r, expected in cases:
            self.assertEqual(color_for_row(r, "oscuro"), expected)

    def test_ambiguous_priority(self):
        from gipler.gui.theme import semantic
        r = _row("a.txt", "identical", "tracked_clean", owner="sin determinar", dest="sin determinar")
        self.assertEqual(color_for_row(r, "oscuro"), semantic("oscuro", "ambiguous"))
        r2 = _row("a.txt", "identical", "tracked_clean", inc=["shared_file"])
        self.assertEqual(color_for_row(r2, "oscuro"), semantic("oscuro", "ambiguous"))

    def test_ignored_stays_ignored(self):
        r = _row("g.txt", "identical", "ignored")
        self.assertNotEqual(color_for_row(r), STATE_COLORS["ambiguous"])


class Phase4AdjustTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w, self.patcher = make_profile_window(self.tmp.name, ROWS, sources=SOURCES)
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.w.close)

    def test_datachanged_on_check_uncheck(self):
        from PySide6.QtTest import QSignalSpy

        w = self.w
        spy = QSignalSpy(w.tree_model.dataChanged)
        idx = w.tree_model.index(0, 0)
        w.tree_model.setData(idx, Qt.Checked, Qt.CheckStateRole)
        self.assertGreaterEqual(spy.count(), 1)
        roles = spy.at(0)[2] if spy.count() else []
        self.assertIn(Qt.CheckStateRole, list(roles))
        w.tree_model.setData(idx, Qt.Unchecked, Qt.CheckStateRole)
        self.assertGreaterEqual(spy.count(), 2)

    def test_selection_change_invalidates_cache(self):
        w = self.w
        w.selection_ctrl.keys.add(("principal", "new.txt"))
        w.ops_cache = ["fake"]
        before = set(w.selection_ctrl.keys)
        w.selection_ctrl.toggle(("principal", "same.txt"))
        w._after_selection_change(before)
        self.assertEqual(w.ops_cache, [])

    def test_no_invalidation_when_unchanged(self):
        w = self.w
        w.ops_cache = ["keep"]
        before = set(w.selection_ctrl.keys)
        w.selection_ctrl.toggle(("principal", "new.txt"))
        w.selection_ctrl.toggle(("principal", "new.txt"))
        w._after_selection_change(set(w.selection_ctrl.keys))
        self.assertEqual(w.ops_cache, ["keep"])

    def test_navigation_does_not_invalidate(self):
        w = self.w
        w.ops_cache = ["keep"]
        idx = w.tree_model.index(0, 0)
        w._on_selection_changed(type("S", (), {"indexes": lambda self: [idx]})(), None)
        self.assertEqual(w.ops_cache, ["keep"])

    def test_cancel_dialog_keeps_cache(self):
        w = self.w
        w.ops_cache = ["keep"]
        from gipler.gui.operations_dialog import OperationsDialog
        dlg = OperationsDialog()
        dlg.set_operations([])
        dlg.reject()
        self.assertEqual(w.ops_cache, ["keep"])

    def test_tabs_and_filters_keep_cache(self):
        w = self.w
        w.ops_cache = ["keep"]
        w.set_destination("addons")
        self.assertEqual(w.ops_cache, ["keep"])
        w.apply_filters()
        self.assertEqual(w.ops_cache, ["keep"])

    def test_selection_sync_no_crash(self):
        w = self.w
        w.tree_model.set_rows([
            _row("a.sh", "modified_in_dev", "tracked_clean"),
            _row("b.txt", "identical", "tracked_clean"),
        ], "principal")
        idx = w.proxy.index(0, 0)
        try:
            w.dev_panel.tree.selectionModel().setCurrentIndex(idx, __import__('PySide6.QtCore', fromlist=['QItemSelectionModel']).QItemSelectionModel.SelectionFlag.Current)
        except TypeError:
            self.fail("setCurrentIndex con SelectionFlag lanzando TypeError")
        w.dest_panel.tree.selectionModel().setCurrentIndex(w.repo_proxy.index(0, 0), __import__('PySide6.QtCore', fromlist=['QItemSelectionModel']).QItemSelectionModel.SelectionFlag.Current)

    def test_click_checkbox_interaction(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint

        w = self.w
        model = w.tree_model
        idx = w.proxy.index(0, 0)
        pos = w.dev_panel.tree.visualRect(idx).topLeft() + QPoint(8, 5)
        QTest.mouseClick(w.dev_panel.tree.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        app.processEvents()
        self.assertEqual(model.data(w.proxy.mapToSource(idx), Qt.CheckStateRole), Qt.CheckState.Checked)

    def test_space_toggles_checkbox(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt

        w = self.w
        idx = w.proxy.index(0, 0)
        w.dev_panel.tree.setCurrentIndex(idx)
        before = w.tree_model.data(w.proxy.mapToSource(idx), Qt.CheckStateRole)
        QTest.keyClick(w.dev_panel.tree.viewport(), Qt.Key_Space)
        app.processEvents()
        after = w.tree_model.data(w.proxy.mapToSource(idx), Qt.CheckStateRole)
        self.assertNotEqual(before, after)

    def test_reanalyze_preserves_selection_but_invalidates_review(self):
        w = self.w
        key = ("principal", "new.txt")
        w.selection_ctrl.keys.add(key)
        w.ops_cache = ["gone"]
        w._prepared_token = object()
        w._authorized_token = w._prepared_token
        w.reanalyze()
        self.assertEqual(w.selection_ctrl.keys, {key})
        self.assertEqual(w.ops_cache, [])
        self.assertIsNone(w._prepared_token)
        self.assertIsNone(w._authorized_token)


if __name__ == "__main__":
    unittest.main()
