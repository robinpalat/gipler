"""Physical workspace inventory tests (temporary trees only)."""
from __future__ import annotations

import os
import tempfile
import unittest

from gipler.workspace import scan_workspace


class WorkspaceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "visible", "nested"))
        os.makedirs(os.path.join(self.root, "private", "nested"))
        for path in (
            "visible/file.dat",
            "visible/nested/inside.txt",
            "private/top.txt",
            "private/nested/inside.txt",
            ".hidden",
        ):
            with open(os.path.join(self.root, path), "w", encoding="utf-8") as file:
                file.write(path)

    def test_inventory_contains_physical_files_and_directories(self):
        inventory = scan_workspace(self.root)
        paths = {entry.path for entry in inventory.included}
        self.assertEqual(len(inventory.excluded), 0)
        self.assertTrue({
            "visible",
            "visible/nested",
            "visible/file.dat",
            "visible/nested/inside.txt",
            "private",
            "private/nested",
            ".hidden",
        }.issubset(paths))

    def test_excluded_directory_and_descendants_have_provenance(self):
        inventory = scan_workspace(self.root, ["private/"])
        included = {entry.path for entry in inventory.included}
        excluded = {entry.path: entry for entry in inventory.excluded}
        self.assertNotIn("private", included)
        self.assertNotIn("private/top.txt", included)
        self.assertEqual(
            set(excluded),
            {"private", "private/nested", "private/top.txt", "private/nested/inside.txt"},
        )
        self.assertFalse(excluded["private"].exclusion_inherited)
        self.assertTrue(excluded["private/nested/inside.txt"].exclusion_inherited)
        self.assertEqual(excluded["private/nested/inside.txt"].exclusion_rule, "private/")

    def test_same_basename_paths_remain_distinct(self):
        inventory = scan_workspace(self.root)
        matches = [entry.path for entry in inventory.included if entry.path.endswith("inside.txt")]
        self.assertEqual(matches, ["private/nested/inside.txt", "visible/nested/inside.txt"])

    def test_symlink_is_listed_without_traversing_target(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "secret.txt"), "w", encoding="utf-8") as file:
            file.write("secret")
        os.symlink(outside.name, os.path.join(self.root, "external-link"))
        inventory = scan_workspace(self.root)
        entries = {entry.path: entry for entry in inventory.included}
        self.assertEqual(entries["external-link"].kind, "symlink")
        self.assertEqual(entries["external-link"].link_target, outside.name)
        self.assertNotIn("external-link/secret.txt", entries)

    def test_invalid_work_directory_fails_explicitly(self):
        with self.assertRaises(NotADirectoryError):
            scan_workspace(os.path.join(self.root, "missing"))


if __name__ == "__main__":
    unittest.main()
