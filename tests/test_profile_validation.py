"""Validación e integridad de perfiles.

Cubre AUD-002/PRF-004 (work_dir), AUD-003/PRF-003 (perfiles corruptos)
y AUD-004/PRF-005 (identidad única de referencias). Usa directorios
temporales aislados; nunca el perfil real.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from gipler.profile import (
    ProfileError,
    Source,
    _validate_work_dir,
    create_profile,
    list_profiles,
    load_profile,
    profile_path,
    save_profile,
)


def _valid_toml(profile_id: str, name: str, work_dir: str, sources: str = "") -> str:
    return (
        "schema = 1\n"
        f'id = "{profile_id}"\n'
        f'name = "{name}"\n'
        f'work_dir = "{work_dir}"\n'
        'created = "2026-01-01T00:00:00+00:00"\n'
        "\n"
        "[view]\n"
        'theme = "oscuro"\n'
        'home_view = "todo"\n'
        'home_repository = ""\n'
        "\n"
        f"{sources}"
    )


def _source_block(source_id: str, name: str, order: int) -> str:
    return (
        "[[sources]]\n"
        f'id = "{source_id}"\n'
        f'name = "{name}"\n'
        'kind = "reference_directory"\n'
        'root = ""\n'
        "enabled = true\n"
        f"order = {order}\n"
        "acts_as_recognizer = true\n"
        "acts_as_destination = false\n"
        'sync_destination = ""\n'
        "sync_enabled = false\n"
        'destination_source_id = ""\n'
        "config = {}\n"
        "\n"
    )


def _write_raw(root: str, profile_id: str, text: str) -> str:
    directory = os.path.join(root, profile_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "profile.toml")
    with open(path, "w", encoding="utf-8") as file:
        file.write(text)
    return path


class WorkDirValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.work)

    def test_empty_work_dir_rejected(self):
        with self.assertRaises(ProfileError) as ctx:
            create_profile("P", "", root=self.root)
        self.assertIn("vacío", str(ctx.exception))
        with self.assertRaises(ProfileError):
            _validate_work_dir("")

    def test_relative_work_dir_rejected(self):
        with self.assertRaises(ProfileError) as ctx:
            create_profile("P", "relative/path", root=self.root)
        self.assertIn("absoluto", str(ctx.exception))
        with self.assertRaises(ProfileError):
            _validate_work_dir("relative/path")

    def test_nonexistent_work_dir_rejected(self):
        missing = os.path.join(self.tmp.name, "no-existe")
        with self.assertRaises(ProfileError) as ctx:
            create_profile("P", missing, root=self.root)
        self.assertIn("no existe", str(ctx.exception))

    def test_valid_work_dir_accepted(self):
        profile = create_profile("P", self.work, root=self.root)
        self.assertEqual(profile.work_dir, os.path.abspath(self.work))
        loaded = load_profile(profile.id, self.root)
        self.assertEqual(loaded.work_dir, os.path.abspath(self.work))

    def test_work_dir_that_is_a_file_rejected(self):
        file_path = os.path.join(self.tmp.name, "file.txt")
        with open(file_path, "w", encoding="utf-8") as file:
            file.write("x")
        with self.assertRaises(ProfileError) as ctx:
            create_profile("P", file_path, root=self.root)
        self.assertIn("no es un directorio", str(ctx.exception))

    def test_work_dir_without_permissions_rejected(self):
        if os.geteuid() == 0:
            self.skipTest("el entorno permite leer cualquier directorio como root")
        locked = os.path.join(self.tmp.name, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        with self.assertRaises(ProfileError) as ctx:
            create_profile("P", locked, root=self.root)
        self.assertIn("permisos", str(ctx.exception))

    def test_load_rejects_empty_work_dir(self):
        profile_id = "vacio00000001"
        _write_raw(self.root, profile_id, _valid_toml(profile_id, "Vacio", ""))
        with self.assertRaises(ProfileError) as ctx:
            load_profile(profile_id, self.root)
        self.assertIn("vacío", str(ctx.exception))

    def test_load_rejects_relative_work_dir(self):
        profile_id = "relativ00001"
        _write_raw(self.root, profile_id, _valid_toml(profile_id, "Rel", "relative/path"))
        with self.assertRaises(ProfileError) as ctx:
            load_profile(profile_id, self.root)
        self.assertIn("absoluto", str(ctx.exception))

    def test_load_rejects_nonexistent_work_dir(self):
        profile_id = "inexist000001"
        missing = os.path.join(self.tmp.name, "no-existe")
        _write_raw(self.root, profile_id, _valid_toml(profile_id, "Inex", missing))
        with self.assertRaises(ProfileError) as ctx:
            load_profile(profile_id, self.root)
        self.assertIn("no existe", str(ctx.exception))


class CorruptProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.work)

    def test_malformed_profile_toml_rejected(self):
        profile = create_profile("Bueno", self.work, root=self.root)
        path = profile_path(profile.id, self.root)
        with open(path, "w", encoding="utf-8") as file:
            file.write("esto no es toml = = =\n")
        with self.assertRaises(ProfileError) as ctx:
            load_profile(profile.id, self.root)
        message = str(ctx.exception)
        self.assertIn(profile.id, message)
        self.assertIn("TOML", message)

    def test_list_reports_corrupt_profile_without_crashing(self):
        good = create_profile("Bueno", self.work, root=self.root)
        bad_id = "corrupto0001"
        _write_raw(self.root, bad_id, "no valid\n")
        report: list[tuple[str, str]] = []
        listed = list_profiles(self.root, report=report)
        self.assertEqual([p.id for p in listed], [good.id])
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0][0], bad_id)
        self.assertIn("TOML", report[0][1])

    def test_create_profile_with_corrupt_profile_present(self):
        bad_id = "corrupto0001"
        _write_raw(self.root, bad_id, "no valid\n")
        profile = create_profile("Nuevo", self.work, root=self.root)
        self.assertTrue(os.path.isfile(profile_path(profile.id, self.root)))
        self.assertIn(profile.id, [p.id for p in list_profiles(self.root)])

    def test_load_does_not_repair_or_overwrite_corrupt_profile(self):
        profile = create_profile("Bueno", self.work, root=self.root)
        path = profile_path(profile.id, self.root)
        with open(path, "w", encoding="utf-8") as file:
            file.write("corrupto = =\n")
        with open(path, "rb") as file:
            before = file.read()
        with self.assertRaises(ProfileError):
            load_profile(profile.id, self.root)
        list_profiles(self.root)
        with open(path, "rb") as file:
            after = file.read()
        self.assertEqual(before, after)


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "profiles")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.work)

    def test_duplicate_source_ids_rejected_on_load(self):
        profile_id = "duplicado001"
        sources = _source_block("src_aaaaaaaa", "Uno", 0) + _source_block(
            "src_aaaaaaaa", "Dos", 1
        )
        _write_raw(self.root, profile_id, _valid_toml(profile_id, "Dup", self.work, sources))
        with self.assertRaises(ProfileError) as ctx:
            load_profile(profile_id, self.root)
        message = str(ctx.exception)
        self.assertIn("duplicado", message)
        self.assertIn("src_aaaaaaaa", message)

    def test_empty_or_invalid_source_id_rejected_on_load(self):
        for index, bad_id in enumerate(("", "../malo", "con espacio")):
            profile_id = f"malo0000000{index}"
            sources = _source_block(bad_id, "Mala", 0)
            _write_raw(
                self.root, profile_id, _valid_toml(profile_id, "Mala", self.work, sources)
            )
            with self.assertRaises(ProfileError):
                load_profile(profile_id, self.root)

    def test_load_existing_profile_with_sources_assignments_exclusions(self):
        profile = create_profile("Completo", self.work, root=self.root)
        profile.add_source(Source(id="src_uno0000", name="Uno"))
        profile.add_source(Source(id="src_dos00000", name="Dos"))
        profile.assign_path("a/b.txt", "src_uno0000")
        profile.exclusions = ["privado/"]
        save_profile(profile, self.root)
        loaded = load_profile(profile.id, self.root)
        self.assertEqual(loaded.id, profile.id)
        self.assertEqual(loaded.name, "Completo")
        self.assertEqual([s.id for s in loaded.sources], ["src_uno0000", "src_dos00000"])
        self.assertEqual(loaded.assignments, {"a/b.txt": "src_uno0000"})
        self.assertEqual(loaded.exclusions, ["privado/"])

    def test_load_does_not_modify_existing_profile(self):
        profile = create_profile("Intacto", self.work, root=self.root)
        profile.add_source(Source(id="src_uno0000", name="Uno"))
        save_profile(profile, self.root)
        path = profile_path(profile.id, self.root)
        with open(path, "rb") as file:
            before = file.read()
        load_profile(profile.id, self.root)
        list_profiles(self.root)
        with open(path, "rb") as file:
            after = file.read()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
