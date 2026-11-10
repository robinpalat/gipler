"""Tests Fase 5 GUI (ejecución en QThread, temporales)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class Phase5Tests(unittest.TestCase):
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
            snapshot={"dev": {}, "repos": {"principal": {}}},
        )
        return self.w

    def test_execute_only_copiable(self):
        w = self._window()
        w.selection_ctrl.keys.add(("principal", "new.txt"))
        ops = w.prepare_operations()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        w.authorize_and_execute(list(ops))
        # Esperar QThread.
        for _ in range(100):
            import time

            app.processEvents()
            if not w.is_executing and getattr(w, "results", []):
                break
            time.sleep(0.05)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")) is False)
        self.assertEqual(open(os.path.join(self.repo, "new.txt")).read(), "new.txt")

    def test_cancel_no_write(self):
        w = self._window()
        w.selection_ctrl.keys.add(("principal", "new.txt"))
        ops = w.prepare_operations()
        from gipler.copy_engine import execute_operations
        res = execute_operations(ops, authorized=False)
        self.assertEqual(res[0]["status"], "cancelada")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))

    def test_blocked_never_executed(self):
        w = self._window()
        with open(os.path.join(self.dev, "local.txt"), "w") as f:
            f.write("DEV")
        with open(os.path.join(self.repo, "local.txt"), "w") as f:
            f.write("REPO")
        w.selection_ctrl.keys.add(("principal", "local.txt"))
        ops = w.prepare_operations()
        self.assertEqual(ops[0].status, "bloqueada")
        w.authorize_and_execute(list(ops))
        self.assertEqual(open(os.path.join(self.repo, "local.txt")).read(), "REPO")

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
