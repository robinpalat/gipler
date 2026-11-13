"""Profile CLI/TUI smoke and safety tests using temporary profile data."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest

from gipler.profile import Source, create_profile, save_profile
from gipler.tui import ProfileState
from gipler.profile_analysis import analyze_profile


class ProfileCliTuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp.name
        self.addCleanup(self._restore_home)
        self.work = os.path.join(self.tmp.name, "work")
        self.reference = os.path.join(self.tmp.name, "reference")
        self.destination = os.path.join(self.tmp.name, "destination")
        for root in (self.work, self.reference, self.destination):
            os.makedirs(root)
        self._write(self.work, "new.txt", "workspace")
        self._write(self.reference, "new.txt", "reference")
        self.profile = create_profile("CLI test", self.work)
        self.profile.sources = [
            Source(
                id="src_cli000001",
                name="Reference",
                root=self.reference,
                sync_destination=self.destination,
                acts_as_destination=True,
                sync_enabled=True,
            )
        ]
        save_profile(self.profile)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    @staticmethod
    def _write(root: str, relative: str, value: str):
        with open(os.path.join(root, relative), "w", encoding="utf-8") as file:
            file.write(value)

    def test_profile_tui_lists_dynamic_views_and_only_prepares(self):
        analysis = analyze_profile(self.profile)
        state = ProfileState(self.profile, analysis)
        self.assertEqual(
            state.views,
            ["inicio", "source:src_cli000001", "excluidos", "indeterminados"],
        )
        home_line = state.render_list()
        self.assertIn("new.txt", home_line)
        state.toggle()
        self.assertEqual(len(state.selection), 1)
        operations = state.prepare()
        self.assertEqual(operations[0].status, "copiable")
        self.assertFalse(os.path.exists(os.path.join(self.destination, "new.txt")))
        state.change_view(1)
        self.assertEqual(state.active_view, "source:src_cli000001")
        self.assertIn("new.txt", state.render_list())
        self.assertIn("A=modified_in_dev", state.render_list())

    def test_cli_profile_commands_report_inventory_without_copy(self):
        from gipler.cli import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["analyze-profile", self.profile.id])
        self.assertEqual(result, 0)
        self.assertIn("new.txt", output.getvalue())
        self.assertIn("Reference [src_cli000001]", output.getvalue())
        self.assertIn("modified_in_dev", output.getvalue())
        self.assertNotIn("Repositorio principal", output.getvalue())

        listing = io.StringIO()
        with contextlib.redirect_stdout(listing):
            result = main(["profile-list"])
        self.assertEqual(result, 0)
        self.assertIn(self.profile.id, listing.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.destination, "new.txt")))


if __name__ == "__main__":
    unittest.main()
