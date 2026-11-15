"""P0-8: identidad histórica, novedad y procedencia de líneas de base."""
from __future__ import annotations

import os
import tempfile
import unittest

from gipler.profile import (
    BaselineEntry,
    BaselineSnapshot,
    BaselineStatus,
    Profile,
    ReferenceRoot,
    Source,
    SourceBaseline,
    capture_source_baseline,
    load_profile,
    save_profile,
)
from gipler.profile_analysis import analyze_profile
from gipler.recognition import MembershipState


class BaselineIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.ref_a = os.path.join(self.tmp.name, "ref-a")
        self.ref_b = os.path.join(self.tmp.name, "ref-b")
        self.other_one = os.path.join(self.tmp.name, "other-one")
        self.other_two = os.path.join(self.tmp.name, "other-two")
        for root in (self.work, self.ref_a, self.ref_b, self.other_one, self.other_two):
            os.makedirs(root)
        self.profile_root = os.path.join(self.tmp.name, "profiles")

    @staticmethod
    def _write(root: str, relative: str, content: str) -> None:
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    def _profile(self, *, source_b_enabled: bool = True) -> Profile:
        return Profile(
            id="p08profile1",
            name="P0-8",
            work_dir=self.work,
            sources=[
                Source(id="src_a", name="A", root=self.ref_a, order=0),
                Source(
                    id="src_b",
                    name="B",
                    root=self.ref_b,
                    enabled=source_b_enabled,
                    order=1,
                ),
            ],
        )

    def _capture(self, profile: Profile, source: Source, other=()) -> None:
        source.baseline = capture_source_baseline(
            self.work,
            source.root,
            source.sync_destination or source.root,
            other,
        )

    @staticmethod
    def _entry(result, path: str):
        return next(item for item in result.entries if item.path == path)

    def test_baseline_in_one_source_prevents_false_new(self):
        profile = self._profile()
        self._capture(profile, profile.sources[0])
        self._write(self.work, "legacy.txt", "legacy in work")
        self._capture(profile, profile.sources[1])

        result = analyze_profile(profile)
        entry = self._entry(result, "legacy.txt")
        self.assertEqual(entry.membership.state, MembershipState.UNKNOWN)
        self.assertFalse(entry.post_baseline_new)
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertFalse(entry.is_unassigned_new)
        self.assertEqual(result.unassigned_new, ())

    def test_recognized_identical_is_not_new_when_other_baseline_lacks_it(self):
        profile = self._profile()
        self._capture(profile, profile.sources[1])
        self._write(self.ref_a, "doc.txt", "same")
        self._write(self.work, "doc.txt", "same")
        self._capture(profile, profile.sources[0])

        result = analyze_profile(profile)
        entry = self._entry(result, "doc.txt")
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.membership.source_ids, ("src_a",))
        self.assertEqual(entry.comparisons["src_a"], "identical")
        self.assertFalse(entry.post_baseline_new)
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertFalse(entry.is_unassigned_new)
        self.assertGreaterEqual(len(entry.baseline_matches), 2)
        self.assertTrue(
            {"work", "reference"}
            <= {match.role for match in entry.baseline_matches}
        )

    def test_absent_in_all_relevant_baselines_is_new(self):
        profile = self._profile()
        for source in profile.sources:
            self._capture(profile, source)
        self._write(self.work, "after.txt", "new")

        result = analyze_profile(profile)
        entry = self._entry(result, "after.txt")
        self.assertEqual(entry.membership.state, MembershipState.UNKNOWN)
        self.assertTrue(entry.post_baseline_new)
        self.assertEqual(entry.baseline_status, BaselineStatus.NEW)
        self.assertTrue(entry.is_unassigned_new)
        self.assertEqual(
            [item.path for item in result.unassigned_new], ["after.txt"]
        )

    def test_without_baselines_there_is_no_novelty_information(self):
        profile = self._profile()
        self._write(self.work, "after.txt", "new")

        result = analyze_profile(profile)
        entry = self._entry(result, "after.txt")
        self.assertFalse(entry.post_baseline_new)
        self.assertIsNone(entry.baseline_status)
        self.assertFalse(entry.is_unassigned_new)

    def test_disabled_baseline_still_counts_as_historical_evidence(self):
        profile = self._profile()
        self._capture(profile, profile.sources[0])
        self._write(self.work, "legacy.txt", "known")
        self._capture(profile, profile.sources[1])
        profile.sources[1].enabled = False

        result = analyze_profile(profile)
        entry = self._entry(result, "legacy.txt")
        self.assertFalse(entry.post_baseline_new)
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertFalse(entry.is_unassigned_new)

    def test_same_identity_known_same_and_known_modified(self):
        profile = self._profile()
        self._write(self.ref_a, "doc.txt", "v1")
        self._write(self.work, "doc.txt", "v1")
        self._capture(profile, profile.sources[0])

        same = self._entry(analyze_profile(profile), "doc.txt")
        self.assertEqual(same.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertFalse(same.post_baseline_new)

        self._write(self.work, "doc.txt", "v2")
        modified = self._entry(analyze_profile(profile), "doc.txt")
        self.assertEqual(modified.baseline_status, BaselineStatus.KNOWN_MODIFIED)
        self.assertFalse(modified.post_baseline_new)
        self.assertEqual(modified.comparisons["src_a"], "modified_in_dev")

    def test_same_hash_in_another_path_is_only_complementary(self):
        profile = self._profile()
        self._write(self.ref_a, "one.txt", "same-content")
        self._capture(profile, profile.sources[0])
        self._write(self.work, "two.txt", "same-content")

        result = analyze_profile(profile)
        entry = self._entry(result, "two.txt")
        self.assertEqual(entry.membership.state, MembershipState.UNKNOWN)
        self.assertEqual(entry.baseline_status, BaselineStatus.NEW)
        self.assertTrue(entry.post_baseline_new)
        self.assertTrue(entry.is_unassigned_new)
        self.assertEqual(
            {match.path for match in entry.content_matches_elsewhere},
            {"one.txt"},
        )
        self.assertEqual(
            entry.content_matches_elsewhere[0].source_id, "src_a"
        )

    def test_same_relative_path_in_distinct_roots_is_not_collapsed(self):
        profile = self._profile()
        self._write(self.other_one, "config.toml", "from-one")
        self._write(self.other_two, "config.toml", "from-two")
        self._capture(
            profile,
            profile.sources[1],
            (
                ReferenceRoot(self.other_one, "src_one", "reference"),
                ReferenceRoot(self.other_two, "src_two", "reference"),
            ),
        )
        self._write(self.work, "config.toml", "dev")

        result = analyze_profile(profile)
        entry = self._entry(result, "config.toml")
        self.assertFalse(entry.post_baseline_new)
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_MODIFIED)
        others = [match for match in entry.baseline_matches if match.role == "reference"]
        self.assertEqual(len(others), 2)
        self.assertEqual({match.source_id for match in others}, {"src_one", "src_two"})
        self.assertEqual({match.root for match in others}, {self.other_one, self.other_two})
        self.assertEqual(len({match.identity for match in others}), 2)
        self.assertEqual(
            profile.sources[1].baseline.other_reference_paths, ("config.toml",)
        )
        self.assertEqual(len(profile.sources[1].baseline.other_references), 2)

    def test_identity_disambiguates_distinct_other_roots(self):
        profile = self._profile()
        self._write(self.other_one, "config.toml", "from-one")
        self._write(self.other_two, "config.toml", "from-two")
        self._capture(
            profile,
            profile.sources[1],
            (
                ReferenceRoot(self.other_one, "src_shared", "other"),
                ReferenceRoot(self.other_two, "src_shared", "other"),
            ),
        )
        self._write(self.work, "config.toml", "dev")

        entry = self._entry(analyze_profile(profile), "config.toml")
        self.assertEqual(len(entry.baseline_matches), 2)
        self.assertEqual(
            {match.root for match in entry.baseline_matches},
            {self.other_one, self.other_two},
        )
        self.assertEqual(
            len({match.identity for match in entry.baseline_matches}), 2
        )
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_MODIFIED)
        self.assertFalse(entry.post_baseline_new)
        self.assertFalse(entry.is_unassigned_new)

    def test_identity_disambiguates_roles_on_same_physical_root(self):
        same = os.path.join(self.tmp.name, "same-root")
        os.makedirs(same)
        self._write(same, "known.txt", "known")
        profile = Profile(
            id="p08sameroot",
            name="P0-8 same root",
            work_dir=same,
            sources=[
                Source(
                    id="src_all",
                    name="All",
                    root=same,
                    sync_destination=same,
                    acts_as_recognizer=False,
                )
            ],
        )
        profile.sources[0].baseline = capture_source_baseline(same, same, same)

        known = self._entry(analyze_profile(profile), "known.txt")
        self.assertEqual(len(known.baseline_matches), 3)
        self.assertEqual(
            [match.role for match in known.baseline_matches],
            ["work", "reference", "destination"],
        )
        self.assertEqual(
            len({match.identity for match in known.baseline_matches}), 3
        )
        self.assertEqual(known.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertFalse(known.post_baseline_new)

        self._write(same, "new-after.txt", "new")
        new = self._entry(analyze_profile(profile), "new-after.txt")
        self.assertEqual(new.baseline_matches, ())
        self.assertEqual(new.baseline_status, BaselineStatus.NEW)
        self.assertTrue(new.post_baseline_new)
        self.assertTrue(new.is_unassigned_new)

    def test_multiple_historical_matches_are_all_preserved(self):
        profile = self._profile()
        self._write(self.ref_a, "doc.txt", "a")
        self._write(self.work, "doc.txt", "a")
        self._capture(profile, profile.sources[0])
        self._write(self.ref_b, "doc.txt", "b")
        self._capture(profile, profile.sources[1])

        entry = self._entry(analyze_profile(profile), "doc.txt")
        identities = {
            (match.source_id, match.role) for match in entry.baseline_matches
        }
        self.assertIn(("src_a", "work"), identities)
        self.assertIn(("src_a", "reference"), identities)
        self.assertIn(("src_b", "reference"), identities)
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_SAME)

    def test_directory_and_symlink_status(self):
        profile = self._profile()
        os.makedirs(os.path.join(self.ref_a, "docs"))
        os.symlink("docs", os.path.join(self.ref_a, "link"))
        self._capture(profile, profile.sources[0])
        os.makedirs(os.path.join(self.work, "docs"))
        os.symlink("other", os.path.join(self.work, "link"))

        result = analyze_profile(profile)
        folder = self._entry(result, "docs")
        link = self._entry(result, "link")
        self.assertEqual(folder.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertEqual(link.baseline_status, BaselineStatus.KNOWN_MODIFIED)
        self.assertFalse(folder.post_baseline_new)
        self.assertFalse(link.post_baseline_new)

    def test_mode_does_not_define_content_identity(self):
        profile = self._profile()
        self._write(self.ref_a, "doc.txt", "same")
        self._write(self.work, "doc.txt", "same")
        self._capture(profile, profile.sources[0])
        os.chmod(os.path.join(self.work, "doc.txt"), 0o600)

        entry = self._entry(analyze_profile(profile), "doc.txt")
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_SAME)

    def test_legacy_other_paths_keep_unknown_content_semantics(self):
        profile = self._profile()
        self._write(self.other_one, "legacy.txt", "other")
        captured = capture_source_baseline(
            self.work, self.ref_b, self.ref_b, (self.other_one,)
        )
        profile.sources[1].baseline = SourceBaseline(
            established_at=captured.established_at,
            work_entries=captured.work_entries,
            reference_entries=captured.reference_entries,
            destination_entries=captured.destination_entries,
            other_reference_paths=("legacy.txt",),
        )
        self._write(self.work, "legacy.txt", "dev")

        entry = self._entry(analyze_profile(profile), "legacy.txt")
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN)
        self.assertFalse(entry.post_baseline_new)
        self.assertTrue(
            any(match.entry is None for match in entry.baseline_matches)
        )

    def test_exclusions_compute_status_without_operational_leakage(self):
        profile = self._profile()
        profile.exclusions = ["excluded/"]
        for source in profile.sources:
            self._capture(profile, source)
        self._write(self.work, "excluded/new.txt", "new")

        result = analyze_profile(profile)
        excluded = next(
            item for item in result.excluded_entries
            if item.path == "excluded/new.txt"
        )
        self.assertEqual(excluded.baseline_status, BaselineStatus.NEW)
        self.assertTrue(excluded.post_baseline_new)
        self.assertTrue(excluded.is_unassigned_new)
        self.assertNotIn(
            "excluded/new.txt", {item.path for item in result.unassigned_new}
        )
        self.assertNotIn("excluded/new.txt", {item.path for item in result.entries})

    def test_explicit_assignment_keeps_precedence_and_baseline(self):
        profile = self._profile()
        self._write(self.ref_a, "doc.txt", "a")
        self._write(self.work, "doc.txt", "a")
        self._capture(profile, profile.sources[0])
        baseline_a = profile.sources[0].baseline
        profile.assign_path("doc.txt", "src_b")

        entry = self._entry(analyze_profile(profile), "doc.txt")
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.membership.source_ids, ("src_b",))
        self.assertEqual(entry.baseline_status, BaselineStatus.KNOWN_SAME)
        self.assertFalse(entry.post_baseline_new)
        self.assertEqual(profile.sources[0].baseline, baseline_a)

    def test_new_capture_roundtrip_preserves_labeled_and_legacy_data(self):
        profile = self._profile()
        self._write(self.ref_a, "known.txt", "known")
        self._capture(
            profile,
            profile.sources[1],
            (ReferenceRoot(self.ref_a, "src_a", "reference"),),
        )
        original = profile.sources[1].baseline
        self.assertIsNotNone(original)
        self.assertEqual(original.other_reference_paths, ("known.txt",))
        self.assertEqual(original.other_references[0].source_id, "src_a")
        self.assertEqual(original.other_references[0].role, "reference")
        self.assertEqual(original.other_references[0].root, self.ref_a)

        save_profile(profile, self.profile_root)
        restored = load_profile(profile.id, self.profile_root)
        self.assertEqual(restored.sources[1].baseline, original)

    def test_old_baseline_without_new_fields_keeps_legacy_behavior(self):
        old = SourceBaseline(
            established_at="2026-01-01T00:00:00+00:00",
            work_entries=(),
            reference_entries=(),
            destination_entries=(),
            other_reference_paths=("legacy.txt",),
        )
        profile = self._profile()
        profile.sources[1].baseline = old
        self._write(self.work, "legacy.txt", "dev")

        save_profile(profile, self.profile_root)
        restored = load_profile(profile.id, self.profile_root)
        baseline = restored.sources[1].baseline
        self.assertEqual(baseline.other_reference_paths, ("legacy.txt",))
        self.assertEqual(baseline.other_references, ())
        self.assertEqual(baseline.work_root, "")
        self.assertEqual(baseline.reference_root, "")
        self.assertEqual(baseline.destination_root, "")

        result = analyze_profile(restored)
        item = self._entry(result, "legacy.txt")
        self.assertEqual(item.baseline_status, BaselineStatus.KNOWN)
        self.assertFalse(item.post_baseline_new)
        self.assertTrue(any(match.entry is None for match in item.baseline_matches))
        self.assertEqual(
            {match.source_id for match in item.baseline_matches}, {"src_b"}
        )

    def test_labeled_snapshot_serialization_is_stable(self):
        profile = self._profile()
        self._write(self.ref_a, "known.txt", "known")
        snapshot = BaselineSnapshot(
            source_id="src_a",
            role="reference",
            root=self.ref_a,
            entries=(
                BaselineEntry("known.txt", "file", 5, 0o644, "hash"),
            ),
        )
        source = profile.sources[1]
        source.baseline = SourceBaseline(
            established_at="2026-01-01T00:00:00+00:00",
            work_entries=(),
            reference_entries=(),
            destination_entries=(),
            other_reference_paths=("known.txt",),
            other_references=(snapshot,),
            work_root=self.work,
            reference_root=self.ref_b,
            destination_root=self.ref_b,
        )
        save_profile(profile, self.profile_root)
        restored = load_profile(profile.id, self.profile_root).sources[1].baseline
        self.assertEqual(restored, source.baseline)


if __name__ == "__main__":
    unittest.main()
