"""Tests Fase 5 GUI (ejecución en QThread, temporales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from .helpers import make_profile, write

app = QApplication.instance() or QApplication([])


class Phase5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile, self.dev, roots = make_profile(
            self.tmp.name,
            work_files={"new.txt": "new\n", "same.txt": "same\n", "local.txt": "dev\n"},
            sources=[{"name": "Ref", "files": {"same.txt": "same\n", "local.txt": "same\n"}}],
            assignments={"new.txt": "src_000000"},
        )
        self.repo = roots["src_000000"]
        write(os.path.join(self.repo, "local.txt"), "local\n")
        self.w = None

    def tearDown(self):
        if self.w:
            self.w.close()
        self.tmp.cleanup()

    def _window(self):
        self.w = GiplerWindow(profile=self.profile)
        return self.w

    def test_execute_only_copiable(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = w.prepare_operations()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        w.authorize_and_execute(list(ops))
        for _ in range(100):
            app.processEvents()
            if not w.is_executing and getattr(w, "results", []):
                break
            time.sleep(0.05)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "new.txt")))
        self.assertEqual(open(os.path.join(self.repo, "new.txt")).read(), "new\n")

    def test_cancel_no_write(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = w.prepare_operations()
        from gipler.copy_engine import execute_operations
        res = execute_operations(ops, authorized=False)
        self.assertEqual(res[0]["status"], "cancelada")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))

    def test_blocked_never_executed(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = w.prepare_operations()
        self.assertEqual(ops[0].status, "copiable")
        # El destino aparece tras la preparación: la ejecución debe bloquearla.
        write(os.path.join(self.repo, "new.txt"), "intruso\n")
        w.authorize_and_execute(list(ops))
        for _ in range(100):
            app.processEvents()
            if not w.is_executing:
                break
            time.sleep(0.05)
        self.assertEqual(open(os.path.join(self.repo, "new.txt")).read(), "intruso\n")

    def test_simultaneous_execution_prevented(self):
        w = self._window()
        w.is_executing = True
        w.authorize_and_execute([])
        self.assertTrue(w.is_executing)

    def test_close_blocked_during_execution(self):
        w = self._window()
        w.is_executing = True
        from PySide6.QtGui import QCloseEvent
        ev = QCloseEvent()
        w.closeEvent(ev)
        self.assertFalse(ev.isAccepted())
        w.is_executing = False


if __name__ == "__main__":
    unittest.main()
