"""Regresión: main.sh idéntico (raíz) vs principal/main.sh huérfano.

Ambos archivos con el mismo nombre pero distinta ruta relativa NO
deben confundirse: la correspondencia es por ruta exacta, nunca por
nombre de archivo ni por basenames.
"""
import os
import tempfile
import unittest

from gipler.analysis import analyze
from tests.helpers import make_repo, write, commit_all


class MainShRegressionTests(unittest.TestCase):
    def test_root_identical_and_nested_new(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        root = tmp.name
        dev = os.path.join(root, "dev")
        os.makedirs(dev)
        main = make_repo(root, "principal")
        addons = make_repo(root, "addons")
        big = "#!/bin/bash\n" + "echo test\n" * 2000
        write(os.path.join(dev, "main.sh"), big)
        write(os.path.join(main, "main.sh"), big)
        write(os.path.join(dev, "principal/main.sh"), "editado")
        commit_all(main)
        _, rows, _ = analyze(dev, main, addons)
        by_path = {(r.destination, r.path): r for r in rows}
        root_row = by_path[("principal", "main.sh")]
        self.assertEqual(root_row.axis_a, "identical")
        nested_row = by_path[("principal", "principal/main.sh")]
        self.assertEqual(nested_row.axis_a, "new_in_dev")
        # Un archivo nunca cambia su estado por el nombre gemelo.
        self.assertEqual(
            open(os.path.join(dev, "main.sh"), "rb").read(),
            open(os.path.join(main, "main.sh"), "rb").read(),
        )
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
