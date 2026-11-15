"""Tests del escáner físico (compartido por el sistema de perfiles)."""
import os
import subprocess
import tempfile
import unittest

from gipler.scanner import scan_tree
from .helpers import commit_all, git, make_repo, write


class ScannerTests(unittest.TestCase):
    def test_file_absent_in_both_sides_but_skip_worktree_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons = make_repo(tmp, "addons")
            write(os.path.join(addons, "default/tp1.xml"), "present in HEAD\n")
            commit_all(addons)
            git(addons, "update-index", "--skip-worktree", "--", "default/tp1.xml")
            os.remove(os.path.join(addons, "default", "tp1.xml"))
            os.rmdir(os.path.join(addons, "default"))
            entries = scan_tree(addons, git=True)
            self.assertIn("default/tp1.xml", entries)
            self.assertFalse(entries["default/tp1.xml"].exists)
            self.assertEqual(entries["default/tp1.xml"].git_state, "tracked_clean")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", addons, "rev-parse", "HEAD:default/tp1.xml"],
                    text=True,
                ).strip(),
                subprocess.check_output(
                    ["git", "-C", addons, "rev-parse", ":default/tp1.xml"],
                    text=True,
                ).strip(),
            )

    def test_executable_bit_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev = os.path.join(tmp, "dev")
            os.makedirs(dev)
            write(os.path.join(dev, "run.sh"), "#!/bin/bash\n", executable=True)
            entries = scan_tree(dev)
            self.assertTrue(entries["run.sh"].executable)


if __name__ == "__main__":
    unittest.main()
