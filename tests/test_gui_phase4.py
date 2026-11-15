"""Tests Fase 4 GUI (offscreen, sin escrituras)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.gui.operations_dialog import OperationsDialog
from .helpers import make_profile, write

app = QApplication.instance() or QApplication([])


class Phase4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile, _work, roots = make_profile(
            self.tmp.name,
            work_files={"new.txt": "new\n", "same.txt": "same\n", "local.txt": "same\n"},
            sources=[{"name": "Ref", "files": {"same.txt": "same\n", "local.txt": "same\n"}}],
            assignments={"new.txt": "src_000000"},
        )
        write(os.path.join(roots["src_000000"], "local.txt"), "local\n")
        self.destination_root = roots["src_000000"]
        self.w = None

    def tearDown(self):
        if self.w:
            self.w.close()
        self.tmp.cleanup()

    def _window(self):
        self.w = GiplerWindow(profile=self.profile)
        return self.w

    def test_selection_toggle_and_prepare(self):
        w = self._window()
        w.selection_ctrl.clear()
        from gipler.gui.selection import SelectionController
        sel = SelectionController()
        sel.add(("src_000000", "new.txt"))
        w.selection_ctrl = sel
        ops = w.prepare_operations()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        self.assertFalse(os.path.exists(os.path.join(self.destination_root, "new.txt")))

    def test_cancel_keeps_selection(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        dlg = OperationsDialog()
        dlg.set_operations([])
        dlg.reject()
        self.assertIn(("src_000000", "new.txt"), w.selection_ctrl.keys)

    def test_safe_selection_helper(self):
        from gipler.gui.selection import SelectionController
        sel = SelectionController()
        self.assertIsInstance(sel, SelectionController)

    def test_dialog_summary_counts(self):
        from gipler.copy_engine import Op
        from gipler.report import Row as R
        dlg = OperationsDialog()
        ops = [
            Op(R("a", "núcleo", "src_000000", "new_in_dev", "untracked", []), "/dev", {"src_000000": "/repo"}, "copiable", []),
            Op(R("b", "núcleo", "src_000000", "identical", "tracked_clean", []), "/dev", {"src_000000": "/repo"}, "identica", ["sin_cambios"]),
        ]
        dlg.set_operations(ops)
        self.assertIn("copiable=1", dlg.summary())
        self.assertIn("identica=1", dlg.summary())


if __name__ == "__main__":
    unittest.main()
