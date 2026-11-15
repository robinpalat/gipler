"""P0-7: exclusion keeps physical presence, membership, assignments and baselines.

Only isolated temporary profiles and directories are used.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest

from gipler.profile import (
    add_exclusion,
    capture_source_baseline,
    load_profile,
    remove_exclusion,
    save_profile,
)
from gipler.profile_analysis import analyze_profile
from gipler.recognition import MembershipState
from .helpers import make_profile, write


def by_path(entries):
    return {entry.path: entry for entry in entries}


def operational_paths(analysis):
    return {
        row.path
        for rows in analysis.rows_by_source.values()
        for row in rows
    }


class ExclusionMembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _profile(self):
        profile, work, roots = make_profile(
            self.tmp.name,
            work_files={
                "a.txt": "a",
                "shared.txt": "shared",
                "assigned.txt": "assigned",
                "baseline.txt": "baseline",
                "dir/child.txt": "child",
            },
            sources=[
                {
                    "id": "src_a",
                    "name": "A",
                    "git": False,
                    "files": {
                        "a.txt": "a",
                        "shared.txt": "a-shared",
                        "assigned.txt": "a-assigned",
                        "baseline.txt": "baseline",
                        "dir/child.txt": "child",
                    },
                },
                {
                    "id": "src_b",
                    "name": "B",
                    "git": False,
                    "files": {
                        "shared.txt": "b-shared",
                        "assigned.txt": "b-assigned",
                    },
                },
            ],
            assignments={"assigned.txt": "src_b"},
        )
        profile = load_profile(profile.id)
        src_a, src_b = profile.sources
        src_a.baseline = capture_source_baseline(work, roots["src_a"])
        src_b.baseline = capture_source_baseline(work, roots["src_b"])
        save_profile(profile)
        os.unlink(os.path.join(roots["src_a"], "baseline.txt"))
        write(os.path.join(work, "new.txt"), "new")
        return load_profile(profile.id), work, roots

    def _analyze_with_exclusion(self, profile, pattern):
        add_exclusion(profile.id, pattern)
        reloaded = load_profile(profile.id)
        return reloaded, analyze_profile(reloaded)

    def test_recognized_file_keeps_membership_when_excluded(self):
        profile, _work, _roots = self._profile()
        reloaded, analysis = self._analyze_with_exclusion(profile, "a.txt")
        excluded = by_path(analysis.excluded_entries)["a.txt"]
        self.assertEqual(excluded.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(excluded.membership.source_ids, ("src_a",))
        self.assertNotIn("a.txt", by_path(analysis.entries))
        self.assertNotIn("a.txt", operational_paths(analysis))
        self.assertNotIn("a.txt", {row.path for row in analysis.operation_rows})
        self.assertNotIn("a.txt", {entry.path for entry in analysis.unassigned_new})
        self.assertNotIn("a.txt", {entry.path for entry in analysis.indeterminate})
        self.assertIn("a.txt", by_path(analysis.inventory.excluded))
        self.assertIn("a.txt", reloaded.exclusions)

    def test_shared_file_keeps_all_memberships_when_excluded(self):
        profile, _work, _roots = self._profile()
        _reloaded, analysis = self._analyze_with_exclusion(profile, "shared.txt")
        excluded = by_path(analysis.excluded_entries)["shared.txt"]
        self.assertEqual(excluded.membership.state, MembershipState.SHARED)
        self.assertEqual(excluded.membership.source_ids, ("src_a", "src_b"))
        self.assertNotIn("shared.txt", by_path(analysis.entries))
        self.assertNotIn("shared.txt", operational_paths(analysis))
        self.assertNotIn("shared.txt", {row.path for row in analysis.operation_rows})
        self.assertNotIn(
            "shared.txt",
            {
                entry.path
                for rows in analysis.source_entries.values()
                for entry in rows
            },
        )

    def test_explicit_assignment_survives_exclusion(self):
        profile, _work, _roots = self._profile()
        reloaded, analysis = self._analyze_with_exclusion(profile, "assigned.txt")
        excluded = by_path(analysis.excluded_entries)["assigned.txt"]
        self.assertEqual(excluded.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(excluded.membership.source_ids, ("src_b",))
        self.assertEqual(reloaded.assignments.get("assigned.txt"), "src_b")

    def test_baseline_claim_survives_exclusion(self):
        profile, _work, _roots = self._profile()
        baseline_before = load_profile(profile.id).sources[0].baseline
        reloaded, analysis = self._analyze_with_exclusion(profile, "baseline.txt")
        excluded = by_path(analysis.excluded_entries)["baseline.txt"]
        self.assertEqual(excluded.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(excluded.membership.source_ids, ("src_a",))
        self.assertIn("baseline.txt", reloaded.sources[0].baseline.reference_paths)
        self.assertEqual(reloaded.sources[0].baseline, baseline_before)

    def test_excluded_file_is_absent_from_comparison_rows(self):
        profile, _work, _roots = self._profile()
        _reloaded, analysis = self._analyze_with_exclusion(profile, "a.txt")
        self.assertNotIn("a.txt", operational_paths(analysis))
        self.assertNotIn("a.txt", by_path(analysis.entries))

    def test_excluded_file_is_not_a_copy_candidate(self):
        profile, _work, _roots = self._profile()
        before = analyze_profile(load_profile(profile.id))
        self.assertIn("baseline.txt", {row.path for row in before.operation_rows})
        _reloaded, analysis = self._analyze_with_exclusion(profile, "baseline.txt")
        self.assertNotIn("baseline.txt", {row.path for row in analysis.operation_rows})
        self.assertNotIn("baseline.txt", {row.path for row in analysis.copy_rows()})

    def test_excluded_new_file_is_not_unassigned(self):
        profile, _work, _roots = self._profile()
        before = analyze_profile(load_profile(profile.id))
        self.assertIn("new.txt", {entry.path for entry in before.unassigned_new})
        _reloaded, analysis = self._analyze_with_exclusion(profile, "new.txt")
        excluded = by_path(analysis.excluded_entries)["new.txt"]
        self.assertEqual(excluded.membership.state, MembershipState.UNKNOWN)
        self.assertTrue(excluded.is_unassigned_new)
        self.assertNotIn("new.txt", {entry.path for entry in analysis.unassigned_new})
        self.assertNotIn("new.txt", by_path(analysis.entries))
        self.assertNotIn("new.txt", {entry.path for entry in analysis.indeterminate})
        self.assertNotIn(
            "new.txt", {entry.path for entry in analysis.membership_review_entries}
        )

    def test_excluded_file_is_visible_in_admin_inventory_with_rule_provenance(self):
        profile, _work, _roots = self._profile()
        add_exclusion(profile.id, "a.txt")
        add_exclusion(profile.id, "dir/")
        analysis = analyze_profile(load_profile(profile.id))
        excluded = by_path(analysis.inventory.excluded)
        self.assertEqual(excluded["a.txt"].exclusion_rule, "a.txt")
        self.assertFalse(excluded["a.txt"].exclusion_inherited)
        self.assertEqual(excluded["dir/child.txt"].exclusion_rule, "dir/")
        self.assertTrue(excluded["dir/child.txt"].exclusion_inherited)

    def test_restore_direct_exclusion_recovers_operational_participation(self):
        profile, _work, _roots = self._profile()
        before = by_path(analyze_profile(load_profile(profile.id)).entries)["a.txt"]
        reloaded, excluded_analysis = self._analyze_with_exclusion(profile, "a.txt")
        self.assertIn("a.txt", by_path(excluded_analysis.excluded_entries))
        remove_exclusion(reloaded.id, "a.txt")
        restored = analyze_profile(load_profile(reloaded.id))
        entry = by_path(restored.entries)["a.txt"]
        self.assertEqual(entry.membership, before.membership)
        self.assertIn("a.txt", operational_paths(restored))
        self.assertNotIn("a.txt", by_path(restored.inventory.excluded))

    def test_restore_inherited_exclusion_recovers_participation(self):
        profile, _work, _roots = self._profile()
        before = by_path(analyze_profile(load_profile(profile.id)).entries)["dir/child.txt"]
        reloaded, excluded_analysis = self._analyze_with_exclusion(profile, "dir/")
        excluded = by_path(excluded_analysis.excluded_entries)["dir/child.txt"]
        self.assertEqual(excluded.membership, before.membership)
        self.assertTrue(
            by_path(excluded_analysis.inventory.excluded)["dir/child.txt"].exclusion_inherited
        )
        self.assertIn("dir/", reloaded.exclusions)
        remove_exclusion(reloaded.id, "dir/")
        restored = analyze_profile(load_profile(reloaded.id))
        entry = by_path(restored.entries)["dir/child.txt"]
        self.assertEqual(entry.membership, before.membership)
        self.assertIn("dir/child.txt", operational_paths(restored))
        self.assertEqual(by_path(restored.inventory.excluded), {})

    def test_excluding_directory_preserves_descendant_membership(self):
        profile, work, _roots = self._profile()
        before = by_path(analyze_profile(load_profile(profile.id)).entries)["dir/child.txt"]
        _reloaded, analysis = self._analyze_with_exclusion(profile, "dir/")
        excluded = by_path(analysis.excluded_entries)["dir/child.txt"]
        self.assertEqual(excluded.membership, before.membership)
        self.assertNotIn("dir/child.txt", by_path(analysis.entries))
        self.assertNotIn("dir/child.txt", operational_paths(analysis))
        self.assertTrue(os.path.isfile(os.path.join(work, "dir", "child.txt")))

    def test_restoring_directory_restores_descendant_participation(self):
        profile, work, _roots = self._profile()
        before = analyze_profile(load_profile(profile.id))
        before_entry = by_path(before.entries)["dir/child.txt"]
        before_rows = {
            source_id: {row.path for row in rows}
            for source_id, rows in before.rows_by_source.items()
        }
        reloaded, _excluded = self._analyze_with_exclusion(profile, "dir/")
        remove_exclusion(reloaded.id, "dir/")
        restored = analyze_profile(load_profile(reloaded.id))
        entry = by_path(restored.entries)["dir/child.txt"]
        self.assertEqual(entry.membership, before_entry.membership)
        self.assertIn("dir/child.txt", operational_paths(restored))
        self.assertEqual(
            {source_id: {row.path for row in rows} for source_id, rows in restored.rows_by_source.items()},
            before_rows,
        )
        self.assertEqual(open(os.path.join(work, "dir", "child.txt")).read(), "child")

    def test_exclude_and_restore_do_not_change_persisted_assignments(self):
        profile, work, _roots = self._profile()
        before = dict(load_profile(profile.id).assignments)
        add_exclusion(profile.id, "assigned.txt")
        self.assertEqual(load_profile(profile.id).assignments, before)
        remove_exclusion(profile.id, "assigned.txt")
        self.assertEqual(load_profile(profile.id).assignments, before)
        self.assertEqual(open(os.path.join(work, "assigned.txt")).read(), "assigned")

    def test_exclude_and_restore_do_not_change_baselines(self):
        profile, _work, _roots = self._profile()
        before = load_profile(profile.id)
        before_baselines = {source.id: source.baseline for source in before.sources}
        add_exclusion(profile.id, "a.txt")
        add_exclusion(profile.id, "dir/")
        after_exclude = load_profile(profile.id)
        self.assertEqual(
            {source.id: source.baseline for source in after_exclude.sources},
            before_baselines,
        )
        remove_exclusion(profile.id, "a.txt")
        remove_exclusion(profile.id, "dir/")
        after_restore = load_profile(profile.id)
        self.assertEqual(
            {source.id: source.baseline for source in after_restore.sources},
            before_baselines,
        )

    def test_route_without_membership_never_acquires_one(self):
        profile, work, _roots = self._profile()
        write(os.path.join(work, "orphan.txt"), "orphan")
        before = by_path(analyze_profile(load_profile(profile.id)).entries)["orphan.txt"]
        self.assertEqual(before.membership.state, MembershipState.UNKNOWN)
        add_exclusion(profile.id, "orphan.txt")
        excluded = by_path(analyze_profile(load_profile(profile.id)).excluded_entries)["orphan.txt"]
        self.assertEqual(excluded.membership.state, MembershipState.UNKNOWN)
        remove_exclusion(profile.id, "orphan.txt")
        restored = by_path(analyze_profile(load_profile(profile.id)).entries)["orphan.txt"]
        self.assertEqual(restored.membership.state, MembershipState.UNKNOWN)
        self.assertNotIn("orphan.txt", load_profile(profile.id).assignments)

    def test_non_excluded_files_keep_identical_operational_behaviour(self):
        profile, _work, _roots = self._profile()
        before = analyze_profile(load_profile(profile.id))
        add_exclusion(profile.id, "a.txt")
        after = analyze_profile(load_profile(profile.id))
        before_entries = by_path(before.entries)
        after_entries = by_path(after.entries)
        self.assertEqual(set(after_entries), set(before_entries) - {"a.txt"})
        for path, entry in after_entries.items():
            self.assertEqual(entry.membership, before_entries[path].membership)
        self.assertEqual(
            operational_paths(after),
            operational_paths(before) - {"a.txt"},
        )
        self.assertEqual(
            {row.path for row in after.operation_rows},
            {row.path for row in before.operation_rows} - {"a.txt"},
        )
        self.assertEqual(
            {entry.path for entry in after.unassigned_new},
            {entry.path for entry in before.unassigned_new},
        )
        self.assertEqual(
            {entry.path for entry in after.indeterminate},
            {entry.path for entry in before.indeterminate},
        )

    def test_gui_admin_page_and_restore_use_domain_membership(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from gipler.gui.main_window import GiplerWindow

        app = QApplication.instance() or QApplication([])
        profile, _work, _roots = self._profile()
        window = GiplerWindow(profile=profile)
        try:
            window.exclude_path("shared.txt", False)
            analysis = window.profile_analysis
            self.assertEqual(
                by_path(analysis.excluded_entries)["shared.txt"].membership.source_ids,
                ("src_a", "src_b"),
            )
            self.assertNotIn("shared.txt", {row.path for row in window.rows})
            page = window._profile_admin_pages["excluidos"]
            entries = {
                page.list.item(index).data(Qt.UserRole).path: page.list.item(index).data(Qt.UserRole)
                for index in range(page.list.count())
            }
            self.assertIn("shared.txt", entries)
            window._restore_profile_exclusion(entries["shared.txt"])
            restored = window.profile_analysis
            self.assertNotIn("shared.txt", by_path(restored.inventory.excluded))
            self.assertEqual(
                by_path(restored.entries)["shared.txt"].membership.source_ids,
                ("src_a", "src_b"),
            )
            self.assertIn("shared.txt", {row.path for row in window.rows})
        finally:
            window.close()

    def test_gui_restore_inherited_never_deletes_directory_rule_silently(self):
        from unittest.mock import patch

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox

        from gipler.gui.main_window import GiplerWindow

        app = QApplication.instance() or QApplication([])
        profile, _work, _roots = self._profile()
        window = GiplerWindow(profile=profile)
        try:
            window.exclude_path("dir", True)
            self.assertIn("dir/", window.profile.exclusions)
            page = window._profile_admin_pages["excluidos"]
            entry = next(
                page.list.item(index).data(Qt.UserRole)
                for index in range(page.list.count())
                if page.list.item(index).data(Qt.UserRole).path == "dir/child.txt"
            )
            with patch(
                "PySide6.QtWidgets.QMessageBox.question",
                return_value=QMessageBox.No,
            ):
                window._restore_profile_exclusion(entry)
            self.assertIn("dir/", window.profile.exclusions)
            self.assertIn(
                "dir/child.txt",
                {item.path for item in window.profile_analysis.inventory.excluded},
            )
            with patch(
                "PySide6.QtWidgets.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ):
                window._restore_profile_exclusion(entry)
            self.assertNotIn("dir/", window.profile.exclusions)
            self.assertIn(
                "dir/child.txt",
                {item.path for item in window.profile_analysis.entries},
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
