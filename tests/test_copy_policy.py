"""P0-10: política única de elegibilidad de copia y motivos previos."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from gipler.copy_engine import build_operations
from gipler.copy_policy import (
    STATUS_BLOCKED,
    STATUS_COPIABLE,
    STATUS_REQUIRES_ASSIGNMENT,
    describe_blockers,
    entry_copy_decision,
    entry_copy_decisions,
)
from gipler.profile_analysis import analyze_profile
from gipler.recognition import MembershipState, RecognitionResult
from gipler.report import Row, tooltip_text, warnings_text
from gipler.tui import ProfileState
from gipler.workspace import WorkspaceEntry
from .helpers import make_profile, write


class CopyPolicyMatrixTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        self.home.cleanup()

    def _entry(
        self,
        *,
        state=MembershipState.RECOGNIZED,
        destinations=("dst",),
        comparison="modified_in_dev",
        git_state="tracked_clean",
        kind="file",
        reasons=(),
        source_ids=("src",),
    ):
        return SimpleNamespace(
            physical=WorkspaceEntry("file.txt", kind, 0, 0o644),
            membership=RecognitionResult(
                state,
                source_ids=tuple(source_ids),
                destination_source_ids=tuple(destinations),
                reasons=tuple(reasons),
            ),
            work_dir=self.root,
            destination_comparisons={item: comparison for item in destinations},
            destination_git_states={item: git_state for item in destinations},
            path="file.txt",
        )

    def test_shared_with_one_destination_requires_assignment(self):
        entry = self._entry(
            state=MembershipState.SHARED,
            destinations=("dst",),
            source_ids=("dst", "recognizer"),
        )
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_REQUIRES_ASSIGNMENT)
        self.assertIn("shared_file", decision.blockers)
        self.assertEqual(entry_copy_decisions(entry), (decision,))

    def test_shared_with_two_destinations_requires_assignment_for_both(self):
        entry = self._entry(
            state=MembershipState.SHARED,
            destinations=("dst_a", "dst_b"),
            source_ids=("dst_a", "dst_b"),
        )
        decisions = entry_copy_decisions(entry)
        self.assertEqual(len(decisions), 2)
        self.assertTrue(
            all(item.status == STATUS_REQUIRES_ASSIGNMENT for item in decisions)
        )
        self.assertTrue(all("shared_file" in item.blockers for item in decisions))

    def test_assignment_makes_shared_copyable_and_engine_agrees(self):
        profile, work, roots = make_profile(
            self.root,
            work_files={"shared.txt": "dev"},
            sources=[
                {
                    "id": "src_a",
                    "name": "A",
                    "files": {"shared.txt": "a"},
                    "acts_as_destination": True,
                },
                {
                    "id": "src_b",
                    "name": "B",
                    "files": {"shared.txt": "b"},
                    "acts_as_destination": False,
                },
            ],
        )
        before = analyze_profile(profile)
        shared = next(entry for entry in before.entries if entry.path == "shared.txt")
        self.assertEqual(shared.membership.state, MembershipState.SHARED)
        self.assertEqual(shared.copy_status, STATUS_REQUIRES_ASSIGNMENT)
        self.assertEqual(before.operation_rows, ())

        profile.assign_path("shared.txt", "src_a")
        after = analyze_profile(profile)
        assigned = next(entry for entry in after.entries if entry.path == "shared.txt")
        self.assertEqual(assigned.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(assigned.copy_status, STATUS_COPIABLE)
        self.assertEqual(assigned.eligible_destination_source_ids, ("src_a",))
        self.assertEqual(len(after.operation_rows), 1)
        row = after.operation_rows[0]
        self.assertEqual(row.selection_key, ("src_a", "shared.txt"))
        ops = build_operations(
            after.operation_rows,
            {(row.destination, row.path)},
            work,
            after.destination_roots,
            after.snapshot,
        )
        self.assertEqual(ops[0].status, "copiable")

    def test_tracked_clean_destination_is_copyable(self):
        entry = self._entry(comparison="modified_in_dev", git_state="tracked_clean")
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_COPIABLE)
        self.assertEqual(decision.blockers, ())

    def test_tracked_modified_destination_is_blocked(self):
        entry = self._entry(comparison="modified_in_dev", git_state="tracked_modified")
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertIn("destino_con_modificacion_local", decision.blockers)

    def test_ignored_destination_is_blocked(self):
        entry = self._entry(comparison="new_in_dev", git_state="ignored")
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertIn("destino_ignorado", decision.blockers)

    def test_untracked_new_destination_is_copyable(self):
        entry = self._entry(comparison="new_in_dev", git_state="untracked")
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_COPIABLE)

    def test_untracked_modified_destination_is_blocked(self):
        entry = self._entry(comparison="modified_in_dev", git_state="untracked")
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertIn("destino_untracked_no_sobrescribir", decision.blockers)

    def test_missing_in_dev_is_blocked(self):
        entry = self._entry(comparison="missing_in_dev", git_state="n/a")
        decision = entry_copy_decision(entry, "dst")
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertIn("missing_in_dev", decision.blockers)

    def test_analysis_omits_git_blocked_rows_even_if_recognized(self):
        profile, _work, roots = make_profile(
            self.root,
            work_files={"mod.txt": "dev"},
            sources=[
                {
                    "id": "src_a",
                    "name": "A",
                    "files": {"mod.txt": "repo"},
                    "acts_as_destination": True,
                }
            ],
        )
        write(os.path.join(roots["src_a"], "mod.txt"), "local")
        analysis = analyze_profile(profile)
        entry = next(item for item in analysis.entries if item.path == "mod.txt")
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.copy_status, STATUS_BLOCKED)
        self.assertIn("destino_con_modificacion_local", entry.copy_blockers)
        self.assertEqual(analysis.operation_rows, ())
        row = next(
            item for item in analysis.rows_by_source["src_a"] if item.path == "mod.txt"
        )
        self.assertIn("destino_con_modificacion_local", row.copy_blockers)

    def test_reasons_are_visible_before_prepare_in_report_and_tui(self):
        row = Row(
            "shared.txt",
            "A",
            "src_a",
            "new_in_dev",
            "untracked",
            ["shared_file"],
            copy_blockers=("shared_file",),
        )
        self.assertIn("Archivo compartido", warnings_text(row))
        self.assertIn("Copia:", tooltip_text(row))
        self.assertIn("Archivo compartido", describe_blockers(row.copy_blockers)[0])

        profile, _work, _roots = make_profile(
            self.root,
            work_files={"shared.txt": "dev"},
            sources=[
                {"id": "src_a", "name": "A", "files": {"shared.txt": "a"}},
                {"id": "src_b", "name": "B", "files": {"shared.txt": "b"}},
            ],
        )
        analysis = analyze_profile(profile)
        state = ProfileState(profile, analysis)
        state.active_view = "inicio"
        state.cursor = next(
            index
            for index, entry in enumerate(state.visible())
            if entry.path == "shared.txt"
        )
        self.assertIn("Copia: Archivo compartido", state.render_profile_detail())


if __name__ == "__main__":
    unittest.main()
