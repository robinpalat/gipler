"""Tests de perfiles: modelo, persistencia TOML y CRUD (HOME no afecta)."""
from __future__ import annotations

import os
import tempfile
import tomllib
import unittest

from gipler import ignore
from gipler.profile import (
    ProfileError,
    Source,
    add_exclusion,
    capture_source_baseline,
    create_profile,
    delete_profile,
    last_profile_id,
    list_profiles,
    load_profile,
    make_profile,
    new_source_id,
    profile_path,
    profiles_root,
    remove_exclusion,
    rename_profile,
    save_profile,
    set_last_profile_id,
)
from gipler.recognition import MembershipState, recognize_path


class ProfileRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def test_root_override_is_absolute(self):
        self.assertEqual(profiles_root(self.root), os.path.abspath(self.root))

    def test_default_root_lives_under_user_config(self):
        default = profiles_root()
        self.assertTrue(default.endswith(os.path.join(".config", "Gipler", "profiles")))

    def test_list_profiles_on_missing_root(self):
        self.assertEqual(list_profiles(self.root), [])


class CreateAndLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def test_create_and_round_trip(self):
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        p = create_profile("Mi perfil", work, root=self.root)
        self.assertTrue(os.path.isfile(profile_path(p.id, self.root)))
        again = load_profile(p.id, self.root)
        self.assertEqual(again.id, p.id)
        self.assertEqual(again.name, "Mi perfil")
        self.assertEqual(again.work_dir, os.path.abspath(work))
        self.assertTrue(again.created)
        self.assertEqual(again.view["home_view"], "todo")
        self.assertEqual(again.exclusions, [])
        self.assertEqual(again.sources, [])

    def test_work_dir_is_normalised(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        self.assertTrue(os.path.isabs(p.work_dir))
        self.assertEqual(p.work_dir, os.path.abspath(self.tmp.name))

    def test_duplicate_name_rejected_case_insensitively(self):
        create_profile("Idiomind", self.tmp.name, root=self.root)
        with self.assertRaises(ProfileError):
            create_profile("  idiomind  ", self.tmp.name, root=self.root)

    def test_empty_name_rejected(self):
        with self.assertRaises(ProfileError):
            create_profile("   ", self.tmp.name, root=self.root)

    def test_relative_work_dir_rejected(self):
        with self.assertRaises(ProfileError):
            create_profile("P", "relative/path", root=self.root)

    def test_empty_work_dir_rejected(self):
        with self.assertRaises(ProfileError):
            create_profile("P", "  ", root=self.root)

    def test_invalid_profile_id_rejected(self):
        with self.assertRaises(ProfileError):
            load_profile("../escape", self.root)

    def test_save_is_idempotent(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        path = profile_path(p.id, self.root)
        with open(path, encoding="utf-8") as f:
            first = f.read()
        save_profile(p, self.root)
        with open(path, encoding="utf-8") as f:
            second = f.read()
        self.assertEqual(first, second)

    def test_no_temporary_files_left_behind(self):
        create_profile("P", self.tmp.name, root=self.root)
        leftovers = [
            n for n in os.listdir(os.path.join(self.root))
            if n.startswith(".tmp-")
        ]
        self.assertEqual(leftovers, [])

    def test_unicode_and_quotes_survive(self):
        p = create_profile('Perfil "raro" \\ y áé', self.tmp.name, root=self.root)
        self.assertEqual(load_profile(p.id, self.root).name, 'Perfil "raro" \\ y áé')

    def test_source_baseline_round_trips_without_migrating_older_sources(self):
        work = os.path.join(self.tmp.name, "work")
        reference = os.path.join(self.tmp.name, "reference")
        destination = os.path.join(self.tmp.name, "destination")
        other_reference = os.path.join(self.tmp.name, "other-reference")
        for root in (work, reference, destination, other_reference):
            os.makedirs(root)
        with open(os.path.join(work, "existing.txt"), "w", encoding="utf-8") as file:
            file.write("work")
        with open(os.path.join(reference, "existing.txt"), "w", encoding="utf-8") as file:
            file.write("reference")
        os.makedirs(os.path.join(reference, ".git"))
        with open(
            os.path.join(reference, ".git", "config"), "w", encoding="utf-8"
        ) as file:
            file.write("git metadata")
        with open(
            os.path.join(destination, "existing-destination.txt"),
            "w",
            encoding="utf-8",
        ) as file:
            file.write("destination")
        with open(
            os.path.join(other_reference, "known-elsewhere.txt"),
            "w",
            encoding="utf-8",
        ) as file:
            file.write("elsewhere")
        profile = create_profile("P", work, root=self.root)
        old_source = Source(id="src_old", name="Anterior", root=reference)
        baseline_source = Source(
            id="src_new",
            name="Nueva",
            root=reference,
            sync_destination=destination,
        )
        baseline_source.baseline = capture_source_baseline(
            work, reference, destination, (other_reference,)
        )
        profile.sources.extend((old_source, baseline_source))
        save_profile(profile, self.root)

        reopened = load_profile(profile.id, self.root)
        self.assertIsNone(reopened.source("src_old").baseline)
        restored = reopened.source("src_new").baseline
        self.assertIsNotNone(restored)
        self.assertTrue(restored.established_at)
        self.assertEqual(
            {entry.path for entry in restored.work_entries},
            {"existing.txt"},
        )
        self.assertEqual(
            {entry.path for entry in restored.reference_entries},
            {"existing.txt"},
        )
        self.assertEqual(
            {entry.path for entry in restored.destination_entries},
            {"existing-destination.txt"},
        )
        self.assertEqual(
            restored.other_reference_paths, ("known-elsewhere.txt",)
        )
        self.assertEqual(
            restored.reference_entries[0].sha256,
            capture_source_baseline(work, reference, destination)
            .reference_entries[0]
            .sha256,
        )


class CorruptAndSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def test_missing_profile_raises(self):
        with self.assertRaises(ProfileError):
            load_profile("noexiste1", self.root)

    def test_unreadable_toml_raises(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        with open(profile_path(p.id, self.root), "w", encoding="utf-8") as f:
            f.write("esto no es toml = = =\n")
        with self.assertRaises(ProfileError):
            load_profile(p.id, self.root)

    def test_future_schema_rejected(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        path = profile_path(p.id, self.root)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("schema = 1", "schema = 99", 1))
        with self.assertRaises(ProfileError):
            load_profile(p.id, self.root)

    def test_id_mismatch_rejected(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        path = profile_path(p.id, self.root)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(f'id = "{p.id}"', 'id = "otro00000000"', 1))
        with self.assertRaises(ProfileError):
            load_profile(p.id, self.root)

    def test_list_skips_corrupt_profile(self):
        good = create_profile("Bueno", self.tmp.name, root=self.root)
        bad_dir = os.path.join(self.root, "corrupto01")
        os.makedirs(bad_dir)
        with open(os.path.join(bad_dir, "profile.toml"), "w", encoding="utf-8") as f:
            f.write("no valid\n")
        listed = list_profiles(self.root)
        self.assertEqual([p.id for p in listed], [good.id])


class RenameAndDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def test_rename_keeps_id_and_directory(self):
        p = create_profile("Viejo", self.tmp.name, root=self.root)
        renamed = rename_profile(p.id, "Nuevo", root=self.root)
        self.assertEqual(renamed.id, p.id)
        self.assertEqual(os.path.basename(os.path.dirname(profile_path(p.id, self.root))), p.id)
        self.assertEqual(load_profile(p.id, self.root).name, "Nuevo")
        self.assertEqual([x.name for x in list_profiles(self.root)], ["Nuevo"])

    def test_rename_to_taken_name_rejected(self):
        create_profile("Uno", self.tmp.name, root=self.root)
        other = create_profile("Dos", self.tmp.name, root=self.root)
        with self.assertRaises(ProfileError):
            rename_profile(other.id, "uno", root=self.root)

    def test_delete_removes_directory(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        self.assertTrue(delete_profile(p.id, self.root))
        self.assertFalse(os.path.isdir(os.path.join(self.root, p.id)))
        self.assertEqual(list_profiles(self.root), [])

    def test_delete_missing_returns_false(self):
        self.assertFalse(delete_profile("noexiste1", self.root))

    def test_delete_clears_last_profile(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        set_last_profile_id(p.id, self.root)
        delete_profile(p.id, self.root)
        self.assertIsNone(last_profile_id(self.root))


class LastProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def test_default_is_none(self):
        self.assertIsNone(last_profile_id(self.root))

    def test_set_and_get(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        set_last_profile_id(p.id, self.root)
        self.assertEqual(last_profile_id(self.root), p.id)

    def test_set_unknown_profile_rejected(self):
        with self.assertRaises(ProfileError):
            set_last_profile_id("noexiste1", self.root)

    def test_clear(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        set_last_profile_id(p.id, self.root)
        set_last_profile_id(None, self.root)
        self.assertIsNone(last_profile_id(self.root))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def _profile(self):
        return create_profile("P", self.tmp.name, root=self.root)

    def test_source_round_trip(self):
        p = self._profile()
        p.add_source(
            Source(
                id=new_source_id(),
                name="Referencia",
                kind="reference_directory",
                root="/srv/ref",
                order=0,
                acts_as_recognizer=True,
                acts_as_destination=True,
                sync_destination="/srv/dest",
                sync_enabled=True,
                config={"pattern": "*.sh", "deep": True, "n": 3},
            )
        )
        save_profile(p, self.root)
        again = load_profile(p.id, self.root)
        self.assertEqual(len(again.sources), 1)
        s = again.sources[0]
        self.assertEqual(s.name, "Referencia")
        self.assertEqual(s.kind, "reference_directory")
        self.assertTrue(s.acts_as_destination)
        self.assertTrue(s.sync_enabled)
        self.assertEqual(s.config, {"pattern": "*.sh", "deep": True, "n": 3})
        self.assertTrue(s.is_destination)

    def test_duplicate_source_id_rejected(self):
        p = self._profile()
        p.add_source(Source(id="src_aaaaaaaa", name="Uno"))
        with self.assertRaises(ProfileError):
            p.add_source(Source(id="src_aaaaaaaa", name="Dos"))

    def test_source_id_and_name_validated(self):
        p = self._profile()
        with self.assertRaises(ProfileError):
            p.add_source(Source(id="../malo", name="X"))
        with self.assertRaises(ProfileError):
            p.add_source(Source(id=new_source_id(), name="   "))

    def test_recognizer_and_destination_split(self):
        p = self._profile()
        p.add_source(
            Source(id="src_onlyrec00", name="Sólo reconoce",
                   acts_as_recognizer=True, acts_as_destination=False, enabled=True)
        )
        p.add_source(
            Source(id="src_onlydst00", name="Sólo destino",
                   acts_as_recognizer=False, acts_as_destination=True,
                   sync_enabled=True)
        )
        p.add_source(
            Source(id="src_disabled0", name="Desactivada",
                   acts_as_recognizer=True, acts_as_destination=True,
                   sync_enabled=True, enabled=False)
        )
        self.assertEqual([s.id for s in p.recognizers()], ["src_onlyrec00"])
        self.assertEqual([s.id for s in p.destinations()], ["src_onlydst00"])

    def test_recognizer_can_explicitly_target_destination_only_source(self):
        p = self._profile()
        p.add_source(
            Source(
                id="src_recognizer",
                name="Recognition",
                destination_source_id="src_destination",
            )
        )
        p.add_source(
            Source(
                id="src_destination",
                name="Destination",
                acts_as_recognizer=False,
                acts_as_destination=True,
                sync_destination="/srv/target",
                sync_enabled=True,
                order=1,
            )
        )
        save_profile(p, self.root)
        again = load_profile(p.id, self.root)
        self.assertEqual(
            again.source("src_recognizer").destination_source_id,
            "src_destination",
        )
        again.remove_source("src_destination")
        self.assertEqual(again.source("src_recognizer").destination_source_id, "")

    def test_remove_source_does_not_touch_disk(self):
        p = self._profile()
        p.add_source(Source(id="src_aaaaaaaa", name="Uno", root="/algo"))
        p.add_source(Source(id="src_bbbbbbbb", name="Dos", root="/otro"))
        save_profile(p, self.root)
        removed = p.remove_source("src_aaaaaaaa")
        self.assertTrue(removed)
        # En memoria cambió; en disco sigue hasta guardar.
        self.assertEqual(len(load_profile(p.id, self.root).sources), 2)
        save_profile(p, self.root)
        self.assertEqual(len(load_profile(p.id, self.root).sources), 1)

    def test_next_source_order(self):
        p = self._profile()
        self.assertEqual(p.next_source_order(), 0)
        p.add_source(Source(id="src_aaaaaaaa", name="Uno", order=0))
        p.add_source(Source(id="src_bbbbbbbb", name="Dos", order=4))
        self.assertEqual(p.next_source_order(), 5)

    def test_source_identity_survives_rename_and_root_change(self):
        p = self._profile()
        source = Source(id="src_stable001", name="Referencia", root="/old/root")
        p.add_source(source)
        source.name = "Renombrada"
        source.root = "/new/root"
        save_profile(p, self.root)
        loaded = load_profile(p.id, self.root).sources[0]
        self.assertEqual(loaded.id, "src_stable001")
        self.assertEqual(loaded.name, "Renombrada")
        self.assertEqual(loaded.root, "/new/root")

    def test_reordering_preserves_disabled_source_and_stable_order(self):
        p = self._profile()
        p.add_source(Source(id="src_first000", name="Primera", order=0))
        p.add_source(Source(id="src_disabled", name="Desactivada", order=1, enabled=False))
        p.add_source(Source(id="src_last0000", name="Última", order=2))
        p.reorder_source("src_last0000", 0)
        save_profile(p, self.root)
        loaded = load_profile(p.id, self.root)
        self.assertEqual(
            [(s.id, s.order, s.enabled) for s in loaded.sources],
            [("src_last0000", 0, True), ("src_first000", 1, True),
             ("src_disabled", 2, False)],
        )

    def test_save_rejects_duplicate_source_ids(self):
        p = self._profile()
        p.sources.append(Source(id="src_same000", name="Uno"))
        p.sources.append(Source(id="src_same000", name="Dos"))
        with self.assertRaises(ProfileError):
            save_profile(p, self.root)


class ExclusionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")

    def test_exclusions_are_isolated_per_profile(self):
        a = create_profile("A", self.tmp.name, root=self.root)
        b = create_profile("B", self.tmp.name, root=self.root)
        add_exclusion(a.id, "privado/", root=self.root)
        self.assertEqual(load_profile(a.id, self.root).exclusions, ["privado/"])
        self.assertEqual(load_profile(b.id, self.root).exclusions, [])

    def test_add_and_remove_round_trip(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        add_exclusion(p.id, "a.txt", root=self.root)
        add_exclusion(p.id, "d/", root=self.root)
        add_exclusion(p.id, "a.txt", root=self.root)  # idempotente
        self.assertEqual(load_profile(p.id, self.root).exclusions, ["a.txt", "d/"])
        remove_exclusion(p.id, "a.txt", root=self.root)
        self.assertEqual(load_profile(p.id, self.root).exclusions, ["d/"])

    def test_empty_exclusion_rejected(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        with self.assertRaises(ProfileError):
            add_exclusion(p.id, "   ", root=self.root)

    def test_exclusions_file_uses_legacy_format(self):
        p = create_profile("P", self.tmp.name, root=self.root)
        add_exclusion(p.id, "x.txt", root=self.root)
        path = os.path.join(profiles_root(self.root), p.id, "exclusions.toml")
        with open(path, "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["exclude"]["patterns"], ["x.txt"])


class IgnorePathParameterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.custom = os.path.join(self.tmp.name, "custom.toml")

    def test_round_trip_on_explicit_path(self):
        ignore.save_patterns(["uno.txt"], self.custom)
        self.assertEqual(ignore.load_patterns(self.custom), ["uno.txt"])
        ignore.add_pattern("dos/", self.custom)
        self.assertEqual(ignore.load_patterns(self.custom), ["uno.txt", "dos/"])

    def test_default_path_untouched_by_explicit_writes(self):
        default = ignore.ignore_path()
        existed = os.path.isfile(default)
        with open(default, "rb") as f:
            before = f.read() if existed else None
        ignore.save_patterns(["uno.txt"], self.custom)
        self.assertEqual(os.path.isfile(default), existed)
        if existed:
            with open(default, "rb") as f:
                self.assertEqual(f.read(), before)

    def test_remove_pattern_writes_only_on_change(self):
        ignore.save_patterns(["uno.txt"], self.custom)
        before = os.stat(self.custom).st_mtime_ns
        self.assertEqual(ignore.remove_pattern("ausente", self.custom), ["uno.txt"])
        self.assertEqual(os.stat(self.custom).st_mtime_ns, before)
        self.assertEqual(ignore.remove_pattern("uno.txt", self.custom), [])

    def test_missing_custom_path_is_empty(self):
        self.assertEqual(ignore.load_patterns(self.custom), [])

    def test_is_excluded_unchanged(self):
        self.assertTrue(ignore.is_excluded("d/x.txt", ["d/"]))
        self.assertFalse(ignore.is_excluded("other.txt", ["d/"]))


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")
        self.profile = create_profile("P", self.tmp.name, root=self.root)
        self.profile.sources = [
            Source(id="src_assign_a", name="A"),
            Source(id="src_assign_b", name="B"),
            Source(id="src_assign_off", name="Sin reconocer", acts_as_recognizer=False),
        ]
        save_profile(self.profile, self.root)

    def _reload(self):
        return load_profile(self.profile.id, self.root)

    def test_assignment_round_trip(self):
        self.profile.assign_path("nuevo/hola.txt", "src_assign_a")
        save_profile(self.profile, self.root)
        self.assertEqual(self._reload().assignments, {"nuevo/hola.txt": "src_assign_a"})

    def test_reassign_replaces_target(self):
        self.profile.assign_path("hola.txt", "src_assign_a")
        self.profile.assign_path("hola.txt", "src_assign_b")
        save_profile(self.profile, self.root)
        self.assertEqual(self._reload().assignments, {"hola.txt": "src_assign_b"})

    def test_unassign(self):
        self.profile.assign_path("hola.txt", "src_assign_a")
        self.assertTrue(self.profile.unassign_path("hola.txt"))
        self.assertFalse(self.profile.unassign_path("hola.txt"))
        save_profile(self.profile, self.root)
        self.assertEqual(self._reload().assignments, {})

    def test_unknown_source_rejected(self):
        with self.assertRaises(ProfileError):
            self.profile.assign_path("hola.txt", "src_missing0")

    def test_disabled_source_rejected(self):
        self.profile.source("src_assign_b").enabled = False
        with self.assertRaises(ProfileError):
            self.profile.assign_path("hola.txt", "src_assign_b")

    def test_non_recognizer_source_rejected(self):
        with self.assertRaises(ProfileError):
            self.profile.assign_path("hola.txt", "src_assign_off")

    def test_invalid_paths_rejected(self):
        for bad in ("", "  ", "/abs.txt", "../escape.txt", "a/../b.txt", "a//b.txt"):
            with self.assertRaises(ProfileError, msg=bad):
                self.profile.assign_path(bad, "src_assign_a")

    def test_removing_source_drops_its_assignments(self):
        self.profile.assign_path("uno.txt", "src_assign_a")
        self.profile.assign_path("dos.txt", "src_assign_b")
        self.profile.remove_source("src_assign_a")
        save_profile(self.profile, self.root)
        self.assertEqual(self._reload().assignments, {"dos.txt": "src_assign_b"})

    def test_save_rejects_assignment_to_missing_source(self):
        self.profile.assignments["hola.txt"] = "src_missing0"
        with self.assertRaises(ProfileError):
            save_profile(self.profile, self.root)

    def test_load_rejects_assignment_to_missing_source(self):
        self.profile.assign_path("hola.txt", "src_assign_a")
        save_profile(self.profile, self.root)
        path = profile_path(self.profile.id, self.root)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                text.replace(
                    'source_id = "src_assign_a"', 'source_id = "src_missing0"'
                )
            )
        with self.assertRaises(ProfileError):
            load_profile(self.profile.id, self.root)

    def test_assignments_toml_block_is_readable(self):
        self.profile.assign_path("a/b.txt", "src_assign_a")
        save_profile(self.profile, self.root)
        with open(profile_path(self.profile.id, self.root), "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(
            data["assignments"], [{"path": "a/b.txt", "source_id": "src_assign_a"}]
        )


class MakeProfileTests(unittest.TestCase):
    def test_make_profile_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "profiles")
            p = make_profile("P", tmp)
            self.assertFalse(os.path.exists(root))
            self.assertFalse(os.path.isdir(profiles_root(root)))

    def test_make_profile_defaults(self):
        p = make_profile("P", "/tmp")
        self.assertTrue(p.id)
        self.assertEqual(p.view["theme"], "oscuro")
        self.assertEqual(p.sources, [])
        self.assertEqual(p.recognizers(), [])


class MembershipResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.reference_a = os.path.join(self.tmp.name, "reference-a")
        self.reference_b = os.path.join(self.tmp.name, "reference-b")
        os.makedirs(os.path.join(self.work, "nested"))
        os.makedirs(os.path.join(self.reference_a, "nested"))
        os.makedirs(os.path.join(self.reference_b, "nested"))
        with open(os.path.join(self.reference_a, "nested", "same.dat"), "w") as f:
            f.write("a")
        with open(os.path.join(self.reference_b, "nested", "same.dat"), "w") as f:
            f.write("b")
        self.sources = [
            Source(
                id="src_reference1",
                name="Reference A",
                root=self.reference_a,
                acts_as_destination=True,
                sync_destination=os.path.join(self.tmp.name, "destination-a"),
                sync_enabled=True,
            ),
            Source(
                id="src_reference2",
                name="Reference B",
                root=self.reference_b,
            ),
        ]
        os.makedirs(self.sources[0].sync_destination)

    def test_reference_provider_recognizes_by_relative_path_not_basename(self):
        result = recognize_path("nested/same.dat", self.sources)
        self.assertEqual(result.state, MembershipState.SHARED)
        self.assertEqual(result.source_ids, ("src_reference1", "src_reference2"))
        self.assertEqual(result.destination_source_id, "src_reference1")
        self.assertEqual(recognize_path("other/same.dat", self.sources).state,
                         MembershipState.UNKNOWN)

    def test_rules_provider_reports_recognized_path_and_exclusive_conflict(self):
        rules = Source(
            id="src_rules0001",
            name="Rules",
            kind="rules",
            config={"patterns": ["docs/**/*.md"]},
        )
        result = recognize_path("docs/guide/start.md", [rules])
        self.assertEqual(result.state, MembershipState.RECOGNIZED)
        exclusive = Source(
            id="src_rules0002",
            name="Exclusive",
            kind="rules",
            config={"patterns": ["nested/**"], "exclusive": True},
        )
        result = recognize_path("nested/same.dat", [*self.sources, exclusive])
        self.assertEqual(result.state, MembershipState.AMBIGUOUS)
        self.assertEqual(result.destination_source_id, None)

    def test_disabled_and_non_recognizer_sources_do_not_claim(self):
        disabled = Source(
            id="src_disabled0",
            name="Disabled",
            kind="rules",
            enabled=False,
            config={"patterns": ["**"]},
        )
        destination_only = Source(
            id="src_destonly0",
            name="Destination only",
            acts_as_recognizer=False,
        )
        self.assertEqual(
            recognize_path("nested/same.dat", [disabled, destination_only]).state,
            MembershipState.UNKNOWN,
        )

    def test_unavailable_destination_does_not_create_copy_target(self):
        sources = [
            Source(id="src_recognizer", name="Recognizes", root=self.reference_a)
        ]
        result = recognize_path("nested/same.dat", sources)
        self.assertEqual(result.state, MembershipState.RECOGNIZED)
        self.assertIsNone(result.destination_source_id)


if __name__ == "__main__":
    unittest.main()
