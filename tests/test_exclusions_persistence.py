"""Integridad de persistencia de exclusiones (P0-5).

Comprueba serialización TOML segura (comillas, barras, saltos, tabs, Unicode,
espacios), atomicidad de la escritura, errores explícitos ante archivos
corruptos y separación entre exclusiones globales y de perfil.
"""
from __future__ import annotations

import os
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from gipler import ignore
from gipler.ignore import PatternsError
from gipler.profile import (
    ProfileError,
    add_exclusion,
    create_profile,
    exclusions_path,
    list_profiles,
    load_profile,
    make_profile,
    remove_exclusion,
    save_profile,
)


class ExclusionsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "exclusions.toml")

    def _read(self, path=None):
        with open(path or self.path, "rb") as file:
            return file.read()

    def _write_raw(self, content, path=None):
        with open(path or self.path, "wb") as file:
            file.write(content)

    # 1
    def test_double_quotes_round_trip(self):
        patterns = ['archivo "raro".txt', 'a"b', '"']
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 2
    def test_single_quotes_round_trip(self):
        patterns = ["archivo 'raro'.txt", "it's", "'''"]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 3
    def test_backslashes_round_trip(self):
        patterns = [r"C:\ruta\archivo.txt", "\\", "a\\b\\c", r"\\servidor\share"]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 4
    def test_newlines_round_trip(self):
        patterns = ["linea1\nlinea2", "\n", "pre\n\npost"]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 5
    def test_tabs_round_trip(self):
        patterns = ["a\tb", "\t", "pre\t\tpost"]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 6
    def test_unicode_and_accents_round_trip(self):
        patterns = ["café/", "niño.txt", "日本語/ファイル", "e\u0301lan"]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 7
    def test_leading_and_trailing_spaces_round_trip(self):
        patterns = ["  con espacios  ", "   ", "\tinicio", "fin\t"]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)

    # 8
    def test_exact_round_trip_of_mixed_patterns(self):
        patterns = [
            "debian/",
            'images/ "img".png',
            r"tools\bin",
            "línea\nnueva.txt",
            "  espacios  ",
            "日本語",
        ]
        ignore.save_patterns(patterns, self.path)
        self.assertEqual(ignore.load_patterns(self.path), patterns)
        with open(self.path, "rb") as file:
            parsed = tomllib.load(file)
        self.assertEqual(parsed["exclude"]["patterns"], patterns)

    # 9
    def test_multiple_special_characters_in_one_pattern(self):
        pattern = 'a"b\\c\td\ne\rf\bg\fh\u0001i'
        ignore.save_patterns([pattern], self.path)
        self.assertEqual(ignore.load_patterns(self.path), [pattern])

    # 10
    def test_corrupt_toml_is_reported_and_left_intact(self):
        root = os.path.join(self.tmp.name, "profiles")
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        profile = create_profile("Perfil", work, root=root)
        path = exclusions_path(profile.id, root)
        corrupt = b"[exclude\npatterns = [ \"roto\"\n"
        self._write_raw(corrupt, path)

        with self.assertRaises(ProfileError) as ctx:
            load_profile(profile.id, root)
        self.assertIn(profile.id, str(ctx.exception))
        self.assertIn(path, str(ctx.exception))

        with self.assertRaises(ProfileError):
            add_exclusion(profile.id, "nuevo/", root=root)
        with self.assertRaises(ProfileError):
            remove_exclusion(profile.id, "roto", root=root)
        with self.assertRaises(PatternsError):
            ignore.add_pattern("nuevo/", path)
        with self.assertRaises(PatternsError):
            ignore.remove_pattern("roto", path)

        self.assertEqual(self._read(path), corrupt)

        report: list[tuple[str, str]] = []
        list_profiles(root, report=report)
        self.assertEqual([item[0] for item in report], [profile.id])

    # 11
    def test_missing_file_is_empty_list(self):
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(ignore.load_patterns(self.path), [])

    # 12
    def test_write_failure_before_replace_keeps_original(self):
        ignore.save_patterns(["original/"], self.path)
        original = self._read()
        with patch("gipler.ignore.os.fsync", side_effect=OSError("fallo simulado")):
            with self.assertRaises(OSError):
                ignore.save_patterns(["nuevo/"], self.path)
        self.assertEqual(self._read(), original)
        leftovers = [n for n in os.listdir(self.tmp.name) if n.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    # 13
    def test_replace_failure_keeps_original_and_no_temporary(self):
        ignore.save_patterns(["original/"], self.path)
        original = self._read()
        with patch("gipler.ignore.os.replace", side_effect=OSError("fallo simulado")):
            with self.assertRaises(OSError):
                ignore.save_patterns(["nuevo/"], self.path)
        self.assertEqual(self._read(), original)
        leftovers = [n for n in os.listdir(self.tmp.name) if n.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    # 14
    def test_global_and_profile_exclusions_stay_separate(self):
        global_path = os.path.join(self.tmp.name, "global-ignore.toml")
        profile_path = os.path.join(self.tmp.name, "perfil", "exclusions.toml")
        ignore.save_patterns(["global/"], global_path)
        ignore.save_patterns(["perfil/"], profile_path)
        self.assertEqual(ignore.load_patterns(global_path), ["global/"])
        self.assertEqual(ignore.load_patterns(profile_path), ["perfil/"])
        ignore.add_pattern("otro-perfil/", profile_path)
        self.assertEqual(ignore.load_patterns(global_path), ["global/"])
        self.assertNotIn(b"otro-perfil/", self._read(global_path))

    # 15
    def test_normal_profile_exclusions_load_correctly(self):
        root = os.path.join(self.tmp.name, "profiles")
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        profile = create_profile("Perfil", work, root=root)
        add_exclusion(profile.id, "tests/", root=root)
        add_exclusion(profile.id, "images/img.11.png", root=root)
        reloaded = load_profile(profile.id, root)
        self.assertEqual(reloaded.exclusions, ["tests/", "images/img.11.png"])
        with open(exclusions_path(profile.id, root), "rb") as file:
            self.assertEqual(
                tomllib.load(file)["exclude"]["patterns"],
                ["tests/", "images/img.11.png"],
            )

    # 16
    def test_loading_does_not_modify_the_file(self):
        root = os.path.join(self.tmp.name, "profiles")
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        profile = make_profile("Perfil", work)
        profile.exclusions = ["tests/"]
        save_profile(profile, root)
        path = exclusions_path(profile.id, root)
        before = self._read(path)
        before_stat = os.stat(path)
        load_profile(profile.id, root)
        self.assertEqual(self._read(path), before)
        self.assertEqual(os.stat(path).st_mtime_ns, before_stat.st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
