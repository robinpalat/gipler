"""Integridad de revisión y autorización (AUD-021/SYNC-006).

Cancelar o cerrar el diálogo de revisión no debe dejar operaciones
residuales ejecutables sin autorización vigente: la ejecución debe
corresponder exactamente al conjunto revisado y autorizado.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from gipler.gui.main_window import GiplerWindow
from .helpers import make_profile, write

app = QApplication.instance() or QApplication([])


class ReviewAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile, self.dev, roots = make_profile(
            self.tmp.name,
            work_files={"new.txt": "new\n", "new2.txt": "new2\n", "same.txt": "same\n"},
            sources=[{"name": "Ref", "files": {"same.txt": "same\n"}}],
            assignments={"new.txt": "src_000000", "new2.txt": "src_000000"},
        )
        self.repo = roots["src_000000"]
        self.w = None

    def tearDown(self):
        if self.w:
            self.w.close()
        self.tmp.cleanup()

    def _window(self):
        self.w = GiplerWindow(profile=self.profile)
        return self.w

    def _prepare(self, w, mode: str) -> list:
        """Prepara con el diálogo simulado: accept, cancel o close (X)."""

        def fake_exec(dialog):
            if mode == "accept":
                dialog.accepted_authorization = True
                dialog.accept()
            elif mode == "close":
                dialog.close()
            else:
                dialog.reject()
            return dialog.result()

        with patch.object(QDialog, "exec", fake_exec):
            return w.prepare_operations(show_dialog=True)

    def _wait_execution(self, w) -> None:
        for _ in range(100):
            app.processEvents()
            if not w.is_executing:
                break
            time.sleep(0.05)

    def test_review_and_authorize_executes(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = self._prepare(w, "accept")
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        self._wait_execution(w)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "new.txt")))
        with open(os.path.join(self.repo, "new.txt")) as f:
            self.assertEqual(f.read(), "new\n")

    def test_cancel_review_executes_nothing(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = self._prepare(w, "cancel")
        self.assertEqual(ops, [])
        self.assertEqual(w.ops_cache, [])
        self._wait_execution(w)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))

    def test_close_dialog_with_x_executes_nothing(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = self._prepare(w, "close")
        self.assertEqual(ops, [])
        self.assertEqual(w.ops_cache, [])
        self._wait_execution(w)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))

    def test_execute_after_cancel_is_blocked(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        self._prepare(w, "cancel")
        w._execute_from_panel()
        self._wait_execution(w)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))
        self.assertIn("revisión autorizada", w.status.currentMessage())

    def test_new_review_after_cancel_executes_only_new_set(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        self._prepare(w, "cancel")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))
        before = set(w.selection_ctrl.keys)
        w.selection_ctrl.keys.discard(("src_000000", "new.txt"))
        w.selection_ctrl.keys.add(("src_000000", "new2.txt"))
        w._after_selection_change(before)
        ops = self._prepare(w, "accept")
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].path, "new2.txt")
        self._wait_execution(w)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "new2.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))

    def test_changing_review_set_invalidates_previous_authorization(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        self._prepare(w, "accept")
        self._wait_execution(w)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "new.txt")))
        before = set(w.selection_ctrl.keys)
        w.selection_ctrl.keys.discard(("src_000000", "new.txt"))
        w.selection_ctrl.keys.add(("src_000000", "new2.txt"))
        w._after_selection_change(before)
        ops = w.prepare_operations(show_dialog=False)
        self.assertEqual([op.path for op in ops], ["new2.txt"])
        w._execute_from_panel()
        self._wait_execution(w)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new2.txt")))
        self.assertIn("revisión autorizada", w.status.currentMessage())

    def test_origin_change_after_review_is_blocked(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = w.prepare_operations(show_dialog=False)
        self.assertEqual(ops[0].status, "copiable")
        write(os.path.join(self.dev, "new.txt"), "modificado tras la revisión\n")
        w.authorize_and_execute(list(ops))
        self._wait_execution(w)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))

    def test_destination_change_after_review_is_blocked(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        ops = w.prepare_operations(show_dialog=False)
        self.assertEqual(ops[0].status, "copiable")
        write(os.path.join(self.repo, "new.txt"), "intruso\n")
        w.authorize_and_execute(list(ops))
        self._wait_execution(w)
        with open(os.path.join(self.repo, "new.txt")) as f:
            self.assertEqual(f.read(), "intruso\n")

    def test_repeated_execution_does_not_duplicate(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        self._prepare(w, "accept")
        self._wait_execution(w)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "new.txt")))
        w._execute_from_panel()
        self._wait_execution(w)
        with open(os.path.join(self.repo, "new.txt")) as f:
            self.assertEqual(f.read(), "new\n")
        self.assertIn("revisión autorizada", w.status.currentMessage())

    def test_close_window_invalidates_review(self):
        w = self._window()
        w.selection_ctrl.keys.add(("src_000000", "new.txt"))
        w.prepare_operations(show_dialog=False)
        self.assertIsNotNone(w._prepared_token)
        w.close()
        self.assertIsNone(w._prepared_token)
        self.assertIsNone(w._authorized_token)
        self.assertEqual(w.ops_cache, [])
        self.assertFalse(os.path.exists(os.path.join(self.repo, "new.txt")))


if __name__ == "__main__":
    unittest.main()
