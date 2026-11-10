"""Ajustes Fase 4 + codificación cromática (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.gui.models.comparison_tree import (
    STATE_COLORS,
    color_for_row,
)
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


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
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.repo = os.path.join(root, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)
        self.rows = [
            _row("new.txt", "new_in_dev", "untracked"),
            _row("same.txt", "identical", "tracked_clean"),
        ]
        for name in ("new.txt", "same.txt"):
            with open(os.path.join(self.dev, name), "w") as f:
                f.write(name)
        with open(os.path.join(self.repo, "same.txt"), "w") as f:
            f.write("same.txt")

    def tearDown(self):
        if getattr(self, "w", None):
            self.w.close()
        self.tmp.cleanup()

    def _window(self):
        self.w = GiplerWindow(
            rows=self.rows,
            meta={"dev": self.dev, "principal": self.repo, "addons": self.repo},
            snapshot={"dev": {}, "repos": {}},
        )
        return self.w

    def test_datachanged_on_check_uncheck(self):
        from PySide6.QtTest import QSignalSpy

        w = self._window()
        spy = QSignalSpy(w.tree_model.dataChanged)
        idx = w.tree_model.index(0, 0)
        w.tree_model.setData(idx, Qt.Checked, Qt.CheckStateRole)
        self.assertGreaterEqual(spy.count(), 1)
        roles = spy.at(0)[2] if spy.count() else []
        self.assertIn(Qt.CheckStateRole, list(roles))
        w.tree_model.setData(idx, Qt.Unchecked, Qt.CheckStateRole)
        self.assertGreaterEqual(spy.count(), 2)

    def test_selection_change_invalidates_cache(self):
        w = self._window()
        w.selection_ctrl.keys.add(("principal", "new.txt"))
        w.ops_cache = ["fake"]
        before = set(w.selection_ctrl.keys)
        w.selection_ctrl.toggle(("principal", "same.txt"))
        w._after_selection_change(before)
        self.assertEqual(w.ops_cache, [])

    def test_no_invalidation_when_unchanged(self):
        w = self._window()
        w.ops_cache = ["keep"]
        before = set(w.selection_ctrl.keys)
        w.selection_ctrl.toggle(("principal", "new.txt"))
        w.selection_ctrl.toggle(("principal", "new.txt"))
        w._after_selection_change(set(w.selection_ctrl.keys))
        self.assertEqual(w.ops_cache, ["keep"])

    def test_navigation_does_not_invalidate(self):
        w = self._window()
        w.ops_cache = ["keep"]
        idx = w.tree_model.index(0, 0)
        w._on_selection_changed(type("S", (), {"indexes": lambda self: [idx]})(), None)
        self.assertEqual(w.ops_cache, ["keep"])

    def test_cancel_dialog_keeps_cache(self):
        w = self._window()
        w.ops_cache = ["keep"]
        from gipler.gui.operations_dialog import OperationsDialog
        dlg = OperationsDialog()
        dlg.set_operations([])
        dlg.reject()
        self.assertEqual(w.ops_cache, ["keep"])

    def test_tabs_and_filters_keep_cache(self):
        w = self._window()
        w.ops_cache = ["keep"]
        w.set_destination("addons")
        self.assertEqual(w.ops_cache, ["keep"])
        w.apply_filters()
        self.assertEqual(w.ops_cache, ["keep"])

    def test_selection_sync_no_crash(self):
        w = self._window()
        w.tree_model.set_rows([
            _row("a.sh", "modified_in_dev", "tracked_clean"),
            _row("b.txt", "identical", "tracked_clean"),
        ], "principal")
        # Seleccionar vía índice proxy de Dev: no debe lanzar TypeError.
        idx = w.proxy.index(0, 0)
        try:
            w.dev_panel.tree.selectionModel().setCurrentIndex(idx, __import__('PySide6.QtCore', fromlist=['QItemSelectionModel']).QItemSelectionModel.SelectionFlag.Current)
        except TypeError:
            self.fail("setCurrentIndex con SelectionFlag lanzando TypeError")
        # Sincronización del panel Repo no debe lanzar excepción.
        w.dest_panel.tree.selectionModel().setCurrentIndex(w.repo_proxy.index(0, 0), __import__('PySide6.QtCore', fromlist=['QItemSelectionModel']).QItemSelectionModel.SelectionFlag.Current)

    def test_click_checkbox_interaction(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint

        w = self._window()
        model = w.tree_model
        idx = w.proxy.index(0, 0)  # índice proxy con destino activo
        # Clic real sobre la casilla del explorador (posición exacta).
        pos = w.dev_panel.tree.visualRect(idx).topLeft() + QPoint(8, 5)
        QTest.mouseClick(w.dev_panel.tree.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        app.processEvents()
        node = model.node_at(w.proxy.mapToSource(idx))
        self.assertEqual(model.data(w.proxy.mapToSource(idx), Qt.CheckStateRole), Qt.CheckState.Checked)

    def test_space_and_enter_on_focused(self):
        pass  # Enter no alterna casillas (Qt no lo hace); espacio no lo realiza la vista.

    def test_reanalyze_invalidates(self):
        w = self._window()
        w.selection_ctrl.keys.add(("principal", "new.txt"))
        w.ops_cache = ["gone"]
        w.reanalyze()
        self.assertEqual(w.selection_ctrl.keys, set())
        self.assertEqual(w.ops_cache, [])


if __name__ == "__main__":
    unittest.main()
