"""Tests ventana de comparación (Fase usabilidad doble clic)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from gipler.gui.comparison_window import ComparisonWindow
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


class ComparisonWindowTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.repo = os.path.join(root, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_modified_text(self):
        with open(os.path.join(self.dev, "a.txt"), "w") as f:
            f.write("l1\nNEW\n")
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("l1\nOLD\n")
        w = ComparisonWindow(_row("a.txt", "modified_in_dev", "tracked_clean"), self.dev, self.repo)
        all_text = " ".join(w.diff.left.item(r).text() for r in range(w.diff.row_count()))
        self.assertIn("NEW", all_text)
        self.assertEqual(w.diff.left.count(), w.diff.right.count())
        w.close()

    def test_identical_and_binary(self):
        with open(os.path.join(self.dev, "i.txt"), "w") as f:
            f.write("same\n")
        with open(os.path.join(self.repo, "i.txt"), "w") as f:
            f.write("same\n")
        w = ComparisonWindow(_row("i.txt", "identical", "tracked_clean"), self.dev, self.repo)
        self.assertIn("idéntico", w.diff.left.item(0).text())
        w.close()
        with open(os.path.join(self.dev, "b.bin"), "wb") as f:
            f.write(b"\x00\x01")
        with open(os.path.join(self.repo, "b.bin"), "wb") as f:
            f.write(b"\x00\x02")
        w2 = ComparisonWindow(_row("b.bin", "modified_in_dev", "tracked_clean"), self.dev, self.repo)
        self.assertIn("binario", w2.diff.left.item(0).text())
        w2.close()

    def test_new_in_dev(self):
        with open(os.path.join(self.dev, "n.txt"), "w") as f:
            f.write("x\n")
        w = ComparisonWindow(_row("n.txt", "new_in_dev", "untracked"), self.dev, self.repo)
        self.assertIn("sin contraparte", w.diff.left.item(0).text())
        w.close()


if __name__ == "__main__":
    unittest.main()
