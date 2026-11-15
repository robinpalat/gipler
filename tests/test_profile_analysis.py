"""Profile-analysis tests use only temporary workspace/reference trees."""
from __future__ import annotations

import os
import tempfile
import unittest

from gipler.profile import Profile, Source, capture_source_baseline
from gipler.profile_analysis import analyze_profile
from gipler.recognition import MembershipState, recognize_path


class ProfileAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.ref_a = os.path.join(self.tmp.name, "ref-a")
        self.ref_b = os.path.join(self.tmp.name, "ref-b")
        for root in (self.work, self.ref_a, self.ref_b):
            os.makedirs(root)
        self._write(self.work, "known.txt", "same")
        self._write(self.work, "shared.txt", "workspace")
        self._write(self.work, "ambiguous.txt", "workspace")
        self._write(self.work, "unclassified.txt", "workspace")
        self._write(self.work, "excluded/private.txt", "private")
        self._write(self.ref_a, "known.txt", "same")
        self._write(self.ref_a, "shared.txt", "a")
        self._write(self.ref_a, "ambiguous.txt", "a")
        self._write(self.ref_b, "shared.txt", "b")
        self._write(self.ref_b, "ambiguous.txt", "b")
        self.profile = Profile(
            id="profile000001",
            name="Test",
            work_dir=self.work,
            sources=[
                Source(
                    id="src_a0000001",
                    name="A",
                    root=self.ref_a,
                    sync_destination=self.ref_a,
                ),
                Source(id="src_b0000002", name="B", root=self.ref_b),
                Source(
                    id="src_exclusive",
                    name="Exclusive rules",
                    kind="rules",
                    config={"patterns": ["ambiguous.txt"], "exclusive": True},
                ),
            ],
            exclusions=["excluded/"],
        )

    @staticmethod
    def _write(root: str, relative: str, content: str) -> None:
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    def test_inventory_is_complete_and_exclusions_are_separate(self):
        result = analyze_profile(self.profile)
        included_paths = {entry.path for entry in result.entries}
        excluded_paths = {entry.path for entry in result.inventory.excluded}
        self.assertIn("known.txt", included_paths)
        self.assertIn("excluded", excluded_paths)
        self.assertIn("excluded/private.txt", excluded_paths)
        self.assertNotIn("excluded/private.txt", included_paths)

    def test_source_tabs_are_dynamic_and_shared_rows_are_reused_by_identity(self):
        result = analyze_profile(self.profile)
        self.assertEqual(
            {entry.path for entry in result.source_entries["src_a0000001"]},
            {"known.txt", "shared.txt", "ambiguous.txt"},
        )
        self.assertIn(
            "shared.txt",
            {entry.path for entry in result.source_entries["src_b0000002"]},
        )
        shared = next(entry for entry in result.entries if entry.path == "shared.txt")
        self.assertEqual(shared.membership.state, MembershipState.SHARED)

    def test_ambiguous_and_unknown_are_indeterminate_but_shared_is_not(self):
        result = analyze_profile(self.profile)
        states = {entry.path: entry.membership.state for entry in result.entries}
        self.assertEqual(states["ambiguous.txt"], MembershipState.AMBIGUOUS)
        self.assertEqual(states["unclassified.txt"], MembershipState.UNKNOWN)
        self.assertEqual(states["shared.txt"], MembershipState.SHARED)
        self.assertEqual(
            {entry.path for entry in result.indeterminate},
            {"ambiguous.txt", "unclassified.txt"},
        )

    def test_copy_candidate_requires_unique_recognized_destination(self):
        self.profile.sources[0].acts_as_destination = True
        self.profile.sources[0].sync_enabled = True
        result = analyze_profile(self.profile)
        by_path = {entry.path: entry for entry in result.entries}
        self.assertIsNone(by_path["known.txt"].eligible_destination_source_id)
        self.assertIsNone(by_path["shared.txt"].eligible_destination_source_id)
        self.assertIn("shared_file", by_path["shared.txt"].copy_blockers)
        self.assertIsNone(by_path["unclassified.txt"].eligible_destination_source_id)
        self.assertIsNone(by_path["ambiguous.txt"].eligible_destination_source_id)

    def test_reference_comparison_preserves_existing_comparator_states(self):
        result = analyze_profile(self.profile)
        known = next(entry for entry in result.entries if entry.path == "known.txt")
        self.assertEqual(known.comparisons, {"src_a0000001": "identical"})
        modified = next(entry for entry in result.entries if entry.path == "shared.txt")
        self.assertEqual(modified.comparisons["src_a0000001"], "modified_in_dev")

    def test_reference_only_files_are_reported_as_missing_in_dev(self):
        self._write(self.ref_a, "orphan/only-in-reference.txt", "reference")
        result = analyze_profile(self.profile)
        row = next(
            row for row in result.rows_by_source["src_a0000001"]
            if row.path == "orphan/only-in-reference.txt"
        )
        self.assertEqual(row.axis_a, "missing_in_dev")
        self.assertEqual(row.axis_b, "n/a")
        self.assertNotIn(
            "orphan/only-in-reference.txt",
            {entry.path for entry in result.entries},
        )

    def test_git_comparison_states_are_scoped_to_recognized_references(self):
        result = analyze_profile(self.profile)
        known = next(entry for entry in result.entries if entry.path == "known.txt")
        self.assertNotIn("src_b0000002", known.comparisons)

    def test_equal_basenames_in_different_paths_resolve_to_distinct_sources(self):
        work = os.path.join(self.tmp.name, "independent-work")
        ref_left = os.path.join(self.tmp.name, "left-reference")
        ref_right = os.path.join(self.tmp.name, "right-reference")
        for root in (work, ref_left, ref_right):
            os.makedirs(root)
        self._write(work, "left/same.txt", "left")
        self._write(work, "right/same.txt", "right")
        self._write(ref_left, "left/same.txt", "left reference")
        self._write(ref_right, "right/same.txt", "right reference")
        profile = Profile(
            id="profile_paths",
            name="Rutas",
            work_dir=work,
            sources=[
                Source(id="src_left", name="Backend", root=ref_left),
                Source(id="src_right", name="Frontend", root=ref_right),
            ],
        )
        result = analyze_profile(profile)
        left = next(
            row for row in result.rows_by_source["src_left"]
            if row.path == "left/same.txt"
        )
        right = next(
            row for row in result.rows_by_source["src_right"]
            if row.path == "right/same.txt"
        )
        self.assertEqual(left.axis_a, "modified_in_dev")
        self.assertEqual(right.axis_a, "modified_in_dev")
        self.assertNotIn(
            "right/same.txt",
            {row.path for row in result.rows_by_source["src_left"]},
        )

    def test_unconfigured_reference_never_uses_the_process_working_directory(self):
        source = Source(id="src_empty_root", name="Sin ruta")
        self.assertEqual(
            recognize_path("tests/test_profile_analysis.py", [source]).state,
            MembershipState.UNKNOWN,
        )

    def test_existing_copy_engine_prepares_arbitrary_profile_destination(self):
        destination = os.path.join(self.tmp.name, "destination")
        os.makedirs(destination)
        self._write(self.work, "new.txt", "new")
        self._write(self.ref_a, "new.txt", "reference")
        self.profile.sources[0].acts_as_destination = True
        self.profile.sources[0].sync_enabled = True
        self.profile.sources[0].sync_destination = destination
        result = analyze_profile(self.profile)
        rows = result.copy_rows()
        from gipler.copy_engine import build_operations

        operations = build_operations(
            rows,
            {("src_a0000001", "new.txt")},
            self.work,
            result.destination_roots,
            result.snapshot,
        )
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].status, "copiable")
        self.assertFalse(os.path.exists(os.path.join(destination, "new.txt")))

    def test_recognition_and_destination_can_be_separate_sources(self):
        destination = os.path.join(self.tmp.name, "independent-destination")
        os.makedirs(destination)
        recognizer = self.profile.sources[0]
        recognizer.destination_source_id = "src_destination"
        target = Source(
            id="src_destination",
            name="Destino único",
            acts_as_recognizer=False,
            acts_as_destination=True,
            sync_enabled=True,
            sync_destination=destination,
            order=3,
        )
        self.profile.sources.append(target)
        result = analyze_profile(self.profile)
        known = next(entry for entry in result.entries if entry.path == "known.txt")
        self.assertEqual(known.membership.source_ids, ("src_a0000001",))
        self.assertEqual(known.eligible_destination_source_id, "src_destination")
        self.assertIn(
            "known.txt",
            {entry.path for entry in result.source_entries["src_destination"]},
        )
        row = next(row for row in result.copy_rows() if row.path == "known.txt")
        self.assertEqual(row.destination, "src_destination")
        self.assertEqual(row.axis_a, "new_in_dev")

    def test_disabled_destination_preserves_recognition_without_copy_target(self):
        destination = os.path.join(self.tmp.name, "disabled-destination")
        os.makedirs(destination)
        recognizer = self.profile.sources[0]
        recognizer.destination_source_id = "src_destination"
        target = Source(
            id="src_destination",
            name="Destino desactivado",
            acts_as_recognizer=False,
            acts_as_destination=True,
            enabled=False,
            sync_enabled=True,
            sync_destination=destination,
        )
        self.profile.sources.append(target)
        result = analyze_profile(self.profile)
        known = next(entry for entry in result.entries if entry.path == "known.txt")
        self.assertEqual(known.membership.state, MembershipState.RECOGNIZED)
        self.assertIsNone(known.eligible_destination_source_id)

    def _baseline_profile(self):
        work = os.path.join(self.tmp.name, "baseline-work")
        ref_a = os.path.join(self.tmp.name, "baseline-a")
        ref_b = os.path.join(self.tmp.name, "baseline-b")
        for root in (work, ref_a, ref_b):
            os.makedirs(root)
        profile = Profile(
            id="baseline_profile",
            name="Baseline",
            work_dir=work,
            sources=[
                Source(
                    id="src_baseline_a",
                    name="A",
                    root=ref_a,
                    acts_as_destination=True,
                    sync_destination=ref_a,
                    sync_enabled=True,
                ),
                Source(
                    id="src_baseline_b",
                    name="B",
                    root=ref_b,
                    acts_as_destination=True,
                    sync_destination=ref_b,
                    sync_enabled=True,
                    order=1,
                ),
            ],
        )
        return profile

    def test_preexisting_reference_file_is_not_claimed_as_new_in_other_reference(self):
        profile = self._baseline_profile()
        self._write(profile.sources[0].root, "legacy.txt", "legacy")
        for source in profile.sources:
            source.baseline = capture_source_baseline(
                profile.work_dir, source.root
            )

        result = analyze_profile(profile)
        entry = next(
            item for item in result.source_entries["src_baseline_a"]
            if item.path == "legacy.txt"
        )
        self.assertEqual(entry.membership.source_ids, ("src_baseline_a",))
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertNotIn(
            "legacy.txt",
            {row.path for row in result.rows_by_source["src_baseline_b"]},
        )
        row = next(
            row for row in result.rows_by_source["src_baseline_a"]
            if row.path == "legacy.txt"
        )
        self.assertEqual(row.axis_a, "missing_in_dev")

    def test_baseline_records_preexisting_paths_from_other_references(self):
        profile = self._baseline_profile()
        self._write(profile.sources[0].root, "legacy.txt", "legacy")
        source_b = profile.sources[1]
        source_b.baseline = capture_source_baseline(
            profile.work_dir,
            source_b.root,
            source_b.sync_destination,
            (profile.sources[0].root,),
        )
        self._write(profile.work_dir, "legacy.txt", "legacy in Dev")

        result = analyze_profile(profile)
        entry = next(item for item in result.entries if item.path == "legacy.txt")
        self.assertIn("legacy.txt", source_b.baseline.other_reference_paths)
        self.assertNotIn(source_b.id, entry.membership.source_ids)
        self.assertNotIn(
            "legacy.txt",
            {row.path for row in result.rows_by_source[source_b.id]},
        )

    def test_post_baseline_file_waits_for_explicit_assignment(self):
        profile = self._baseline_profile()
        for source in profile.sources:
            source.baseline = capture_source_baseline(
                profile.work_dir, source.root
            )
        self._write(profile.work_dir, "after-baseline.txt", "new")

        result = analyze_profile(profile)
        entry = next(
            item for item in result.entries if item.path == "after-baseline.txt"
        )
        # Sin asignar: no se reparte automáticamente entre las referencias.
        self.assertEqual(entry.membership.state, MembershipState.UNKNOWN)
        self.assertTrue(entry.post_baseline_new)
        self.assertTrue(entry.is_unassigned_new)
        self.assertEqual(
            [item.path for item in result.unassigned_new], ["after-baseline.txt"]
        )
        self.assertNotIn(entry, result.indeterminate)
        for source_id in ("src_baseline_a", "src_baseline_b"):
            self.assertNotIn(
                "after-baseline.txt",
                {row.path for row in result.rows_by_source[source_id]},
            )
        self.assertFalse(
            os.path.exists(
                os.path.join(profile.sources[0].root, "after-baseline.txt")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(profile.sources[1].root, "after-baseline.txt")
            )
        )

        # La asignación explícita crea pertenencia sólo a la referencia elegida.
        profile.assign_path("after-baseline.txt", "src_baseline_a")
        result = analyze_profile(profile)
        entry = next(
            item for item in result.entries if item.path == "after-baseline.txt"
        )
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.membership.source_ids, ("src_baseline_a",))
        self.assertEqual(entry.comparisons["src_baseline_a"], "new_in_dev")
        self.assertEqual(result.unassigned_new, ())
        self.assertNotIn(
            "after-baseline.txt",
            {row.path for row in result.rows_by_source["src_baseline_b"]},
        )
        row_a = next(
            row for row in result.rows_by_source["src_baseline_a"]
            if row.path == "after-baseline.txt"
        )
        self.assertEqual(row_a.axis_a, "new_in_dev")

        from gipler.gui.models.comparison_tree import color_for_row
        from gipler.gui.theme import semantic

        self.assertEqual(color_for_row(row_a), semantic("oscuro", "new_in_dev"))
        self.assertFalse(
            os.path.exists(
                os.path.join(profile.sources[0].root, "after-baseline.txt")
            )
        )

    def test_second_baseline_does_not_claim_into_first_source(self):
        profile = self._baseline_profile()
        first = profile.sources[0]
        second = profile.sources[1]
        first.baseline = capture_source_baseline(profile.work_dir, first.root)
        original_first_baseline = first.baseline
        self._write(profile.work_dir, "between-baselines.txt", "new for A")
        self._write(second.root, "between-baselines.txt", "baseline in B")
        second.baseline = capture_source_baseline(profile.work_dir, second.root)

        result = analyze_profile(profile)
        entry = next(
            item for item in result.entries if item.path == "between-baselines.txt"
        )
        # B ya lo tenía en su línea de base: pertenencia válida a B, no a A.
        self.assertEqual(set(entry.membership.source_ids), {second.id})
        self.assertFalse(entry.is_unassigned_new)
        self.assertEqual(first.baseline, original_first_baseline)
        self.assertIn(
            "between-baselines.txt",
            second.baseline.reference_paths,
        )
        self.assertNotIn(
            "between-baselines.txt",
            {row.path for row in result.rows_by_source[first.id]},
        )
        second_row = next(
            row for row in result.rows_by_source[second.id]
            if row.path == "between-baselines.txt"
        )
        self.assertEqual(second_row.axis_a, "modified_in_dev")

    def test_ambiguous_post_baseline_file_remains_ambiguous_and_ineligible(self):
        profile = self._baseline_profile()
        source = profile.sources[0]
        source.baseline = capture_source_baseline(profile.work_dir, source.root)
        for order, source_id in enumerate(("src_exclusive_new", "src_exclusive_two"), start=2):
            profile.sources.append(
                Source(
                    id=source_id,
                    name=f"Regla exclusiva {order}",
                    kind="rules",
                    config={"patterns": ["ambiguous-new.txt"], "exclusive": True},
                    order=order,
                )
            )
        self._write(profile.work_dir, "ambiguous-new.txt", "new")

        result = analyze_profile(profile)
        entry = next(
            item for item in result.entries if item.path == "ambiguous-new.txt"
        )
        self.assertEqual(
            set(entry.membership.source_ids),
            {"src_exclusive_new", "src_exclusive_two"},
        )
        self.assertEqual(entry.membership.state, MembershipState.AMBIGUOUS)
        self.assertEqual(entry.eligible_destination_source_ids, ())
        self.assertFalse(entry.is_unassigned_new)
        self.assertIn(entry, result.indeterminate)
        self.assertIn(entry, result.membership_review_entries)
        row = next(
            row for row in result.rows_by_source["src_exclusive_new"]
            if row.path == "ambiguous-new.txt"
        )
        self.assertIn("ambiguous", row.incidences)
        from gipler.gui.models.comparison_tree import color_for_row
        from gipler.gui.theme import semantic

        self.assertEqual(color_for_row(row), semantic("oscuro", "ambiguous"))


if __name__ == "__main__":
    unittest.main()
