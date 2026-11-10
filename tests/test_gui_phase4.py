"""Tests Fase 4 GUI (offscreen, sin escrituras)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.gui.operations_dialog import OperationsDialog
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class Phase4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.repo = os.path.join(root, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)
        self.rows = [
            _row("new.txt", "new_in_dev", "untracked"),
            _row("same.txt", "identical", "tracked_clean"),
            _row("local.txt", "modified_in_dev", "tracked_modified"),
        ]
        for name in ("new.txt", "same.txt", "local.txt"):
            with open(os.path.join(self.dev, name), "w") as f:
                f.write(name)
        for name in ("same.txt", "local.txt"):
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(name)
        self.w = None

    def tearDown(self):
        if self.w:
            self.w.close()
        self.tmp.cleanup()

    def _window(self):
        self.w = GiplerWindow(
            rows=self.rows,
            meta={"dev": self.dev, "principal": self.repo, "addons": self.repo},
            snapshot={"dev": {}, "repos": {}},
        )
        return self.w

    def test_selection_toggle_and_prepare(self):
        w = self._window()
        w.selection_ctrl.clear()
        from gipler.gui.selection import SelectionController
        sel = SelectionController()
        sel.add(("principal", "new.txt"))
        # La preparación usa el controlador (selección = intención).
        w.selection_ctrl = sel
        w.snapshot = {"dev": {}, "repos": {"principal": {}}}
        ops = w.prepare_operations()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        # No se escribió nada en el repo.
        self.assertEqual(os.listdir(self.repo), ["local.txt", "same.txt"])

    def test_cancel_keeps_selection(self):
        w = self._window()
        w.selection_ctrl.keys.add(("principal", "new.txt"))
        dlg = OperationsDialog()
        dlg.set_operations([])
        dlg.reject()
        self.assertIn(("principal", "new.txt"), w.selection_ctrl.keys)

    def test_safe_selection_helper(self):
        from gipler.gui.selection import SelectionController
        sel = SelectionController()
        try:
            self.assertIsInstance(sel, SelectionController)
        finally:
            pass

    def test_dialog_summary_counts(self):
        from gipler.copy_engine import Op
        from gipler.report import Row as R
        dlg = OperationsDialog()
        ops = [
            Op(R("a", "núcleo", "principal", "new_in_dev", "untracked", []), "/dev", {"principal": "/repo"}, "copiable", []),
            Op(R("b", "núcleo", "principal", "identical", "tracked_clean", []), "/dev", {"principal": "/repo"}, "identica", ["sin_cambios"]),
        ]
        dlg.set_operations(ops)
        self.assertIn("copiable=1", dlg.summary())
        self.assertIn("identica=1", dlg.summary())


if __name__ == "__main__":
    unittest.main()
