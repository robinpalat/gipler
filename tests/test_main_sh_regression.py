"""Regresión: main.sh idéntico (raíz) vs principal/main.sh anidado.

Ambos archivos con el mismo nombre pero distinta ruta relativa NO
deben confundirse: la correspondencia es por ruta exacta.
"""
import os
import tempfile
import unittest

from gipler.profile_analysis import analyze_profile
from .helpers import make_profile


class MainShRegressionTests(unittest.TestCase):
    def test_root_identical_and_nested_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = "#!/bin/bash\n" + "echo test\n" * 2000
            profile, work, roots = make_profile(
                tmp,
                work_files={"main.sh": big, "principal/main.sh": "editado"},
                sources=[{"name": "Repo", "files": {"main.sh": big}}],
                assignments={"principal/main.sh": "src_000000"},
            )
            analysis = analyze_profile(profile)
            rows = [
                row
                for source_rows in analysis.rows_by_source.values()
                for row in source_rows
            ]
            by_path = {row.path: row for row in rows}
            self.assertEqual(by_path["main.sh"].axis_a, "identical")
            self.assertEqual(by_path["principal/main.sh"].axis_a, "new_in_dev")
            self.assertEqual(
                open(os.path.join(work, "main.sh"), "rb").read(),
                open(os.path.join(roots["src_000000"], "main.sh"), "rb").read(),
            )


if __name__ == "__main__":
    unittest.main()
