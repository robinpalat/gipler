"""Transferencia explícita de membresía (AUD-005 / MEM-006).

La desaparición física de un archivo en una referencia no transfiere su
pertenencia histórica. La baseline de A sigue reclamando la ruta y, sin
asignación explícita, el resultado es SHARED. La asignación explícita a B
prevalece, deja RECOGNIZED a B y no altera la baseline histórica ni autoriza
copias por sí sola.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.profile import (
    Profile,
    ProfileError,
    Source,
    capture_source_baseline,
    load_profile,
    save_profile,
)
from gipler.profile_analysis import analyze_profile
from gipler.recognition import MembershipState

APP = QApplication.instance() or QApplication([])


def _write(root: str, relative: str, text: str) -> None:
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(text)


def _read(root: str, relative: str) -> str:
    with open(os.path.join(root, *relative.split("/")), encoding="utf-8") as file:
        return file.read()


class MembershipTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    def _scenario(self):
        """A tenía documento.txt en su baseline; ahora desaparece de A y
        aparece en B. Dev conserva el archivo con otro contenido."""
        work = os.path.join(self.tmp.name, "work")
        ref_a = os.path.join(self.tmp.name, "ref-a")
        ref_b = os.path.join(self.tmp.name, "ref-b")
        for root in (work, ref_a, ref_b):
            os.makedirs(root)
        _write(ref_a, "documento.txt", "doc-a")
        _write(work, "documento.txt", "doc-dev")
        _write(ref_a, "otro.txt", "otro")
        _write(work, "otro.txt", "otro")
        _write(work, "suelto.txt", "suelto")

        profile = Profile(
            id="membership_transfer",
            name="Transferencia de membresía",
            work_dir=work,
            sources=[
                Source(
                    id="src_a",
                    name="A",
                    root=ref_a,
                    order=0,
                    acts_as_destination=True,
                    sync_destination=ref_a,
                    sync_enabled=True,
                ),
                Source(
                    id="src_b",
                    name="B",
                    root=ref_b,
                    order=1,
                    acts_as_destination=True,
                    sync_destination=ref_b,
                    sync_enabled=True,
                ),
            ],
        )
        source_a, source_b = profile.sources
        source_a.baseline = capture_source_baseline(work, ref_a)
        source_b.baseline = capture_source_baseline(work, ref_b)
        baseline_a = source_a.baseline
        baseline_b = source_b.baseline

        os.unlink(os.path.join(ref_a, "documento.txt"))
        _write(ref_b, "documento.txt", "doc-b")
        return profile, work, ref_a, ref_b, baseline_a, baseline_b

    @staticmethod
    def _entry(result, path):
        return next(entry for entry in result.entries if entry.path == path)

    @staticmethod
    def _row_sources(result, path):
        return {
            source_id
            for source_id, rows in result.rows_by_source.items()
            if any(row.path == path for row in rows)
        }

    @staticmethod
    def _memberships(result):
        return {
            entry.path: (entry.membership.state.value, entry.membership.source_ids)
            for entry in result.entries
        }

    def _persisted_window(self):
        profile, work, ref_a, ref_b, baseline_a, baseline_b = self._scenario()
        save_profile(profile)
        window = GiplerWindow(profile=load_profile(profile.id))
        self.addCleanup(window.close)
        return window, profile, ref_a, ref_b, baseline_a, baseline_b

    @staticmethod
    def _item_for_path(page, path):
        for index in range(page.list.count()):
            item = page.list.item(index)
            entry = item.data(Qt.UserRole)
            if getattr(entry, "path", None) == path:
                return item
        return None

    # 1
    def test_01_baseline_claim_survives_physical_disappearance(self):
        profile, *_ = self._scenario()
        result = analyze_profile(profile)
        entry = self._entry(result, "documento.txt")
        self.assertIn("src_a", entry.membership.source_ids)
        self.assertIn("documento.txt", profile.sources[0].baseline.reference_paths)
        self.assertIn("src_a", self._row_sources(result, "documento.txt"))
        self.assertTrue(
            os.path.exists(os.path.join(profile.sources[1].root, "documento.txt"))
        )
        self.assertFalse(
            os.path.exists(os.path.join(profile.sources[0].root, "documento.txt"))
        )

    # 2
    def test_02_disappearance_is_not_an_automatic_transfer(self):
        profile, *_ = self._scenario()
        result = analyze_profile(profile)
        entry = self._entry(result, "documento.txt")
        self.assertEqual(entry.membership.state, MembershipState.SHARED)
        self.assertIn("src_a", entry.membership.source_ids)
        self.assertNotEqual(entry.membership.source_ids, ("src_b",))
        self.assertEqual(profile.assignments, {})

    # 3
    def test_03_shared_preserves_both_source_ids(self):
        profile, *_ = self._scenario()
        entry = self._entry(analyze_profile(profile), "documento.txt")
        self.assertEqual(entry.membership.state, MembershipState.SHARED)
        self.assertEqual(entry.membership.source_ids, ("src_a", "src_b"))

    # 4
    def test_04_explicit_assignment_recognizes_b(self):
        profile, *_ = self._scenario()
        profile.assign_path("documento.txt", "src_b")
        entry = self._entry(analyze_profile(profile), "documento.txt")
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.membership.source_ids, ("src_b",))

    # 5
    def test_05_a_stops_being_a_current_member(self):
        profile, *_ = self._scenario()
        profile.assign_path("documento.txt", "src_b")
        result = analyze_profile(profile)
        entry = self._entry(result, "documento.txt")
        self.assertNotIn("src_a", entry.membership.source_ids)
        self.assertNotIn("src_a", entry.comparisons)
        self.assertNotIn(
            "documento.txt",
            {row.path for row in result.rows_by_source["src_a"]},
        )

    # 6
    def test_06_assignment_persists_after_save_and_reload(self):
        profile, work, ref_a, ref_b, baseline_a, baseline_b = self._scenario()
        profile.assign_path("documento.txt", "src_b")
        root = os.path.join(self.tmp.name, "profiles")
        save_profile(profile, root=root)
        reloaded = load_profile(profile.id, root=root)
        self.assertEqual(reloaded.assignments, {"documento.txt": "src_b"})
        entry = self._entry(analyze_profile(reloaded), "documento.txt")
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.membership.source_ids, ("src_b",))

    # 7
    def test_07_baseline_a_is_exactly_unchanged(self):
        profile, work, ref_a, ref_b, baseline_a, baseline_b = self._scenario()
        profile.assign_path("documento.txt", "src_b")
        root = os.path.join(self.tmp.name, "profiles")
        save_profile(profile, root=root)
        reloaded = load_profile(profile.id, root=root)
        self.assertEqual(profile.sources[0].baseline, baseline_a)
        self.assertEqual(reloaded.sources[0].baseline, baseline_a)
        self.assertEqual(reloaded.sources[1].baseline, baseline_b)
        self.assertIn("documento.txt", reloaded.sources[0].baseline.reference_paths)

    # 8
    def test_08_disabled_or_invalid_target_grants_no_membership(self):
        profile, *_ = self._scenario()
        source_b = profile.sources[1]

        source_b.enabled = False
        with self.assertRaises(ProfileError):
            profile.assign_path("documento.txt", "src_b")
        self.assertNotIn("documento.txt", profile.assignments)
        entry = self._entry(analyze_profile(profile), "documento.txt")
        self.assertNotIn("src_b", entry.membership.source_ids)

        source_b.enabled = True
        source_b.acts_as_recognizer = False
        with self.assertRaises(ProfileError):
            profile.assign_path("documento.txt", "src_b")
        self.assertNotIn("documento.txt", profile.assignments)
        entry = self._entry(analyze_profile(profile), "documento.txt")
        self.assertNotIn("src_b", entry.membership.source_ids)

        with self.assertRaises(ProfileError):
            profile.assign_path("documento.txt", "src_missing")

        # Asignación persistida a una fuente que luego queda deshabilitada.
        source_b.acts_as_recognizer = True
        profile.assignments["documento.txt"] = "src_b"
        source_b.enabled = False
        entry = self._entry(analyze_profile(profile), "documento.txt")
        self.assertNotIn("src_b", entry.membership.source_ids)
        self.assertEqual(entry.membership.source_ids, ("src_a",))

        profile.assignments["documento.txt"] = "src_missing"
        source_b.enabled = True
        entry = self._entry(analyze_profile(profile), "documento.txt")
        self.assertNotIn("src_missing", entry.membership.source_ids)
        self.assertIn("src_a", entry.membership.source_ids)

    # 9
    def test_09_assignment_does_not_authorize_copy(self):
        window, profile, ref_a, ref_b, baseline_a, baseline_b = (
            self._persisted_window()
        )
        original_b = _read(ref_b, "documento.txt")
        window._assign_new_file("documento.txt", "src_b")
        self.assertEqual(
            load_profile(profile.id).assignments,
            {"documento.txt": "src_b"},
        )
        window.selection_ctrl.keys.add(("src_b", "documento.txt"))
        window._after_selection_change(set())
        self.assertIsNone(window._authorized_token)
        operations = window.prepare_operations(show_dialog=False)
        self.assertEqual(
            [(op.path, op.destination, op.status) for op in operations],
            [("documento.txt", "src_b", "copiable")],
        )
        self.assertIsNone(window._authorized_token)
        window._execute_from_panel()
        APP.processEvents()
        self.assertEqual(_read(ref_b, "documento.txt"), original_b)
        self.assertFalse(os.path.exists(os.path.join(ref_a, "documento.txt")))
        self.assertIn("revisión autorizada", window.status.currentMessage())

    # 10
    def test_10_other_paths_and_memberships_do_not_change(self):
        profile, *_ = self._scenario()
        before = self._memberships(analyze_profile(profile))
        profile.assign_path("documento.txt", "src_b")
        after = self._memberships(analyze_profile(profile))
        for path in ("otro.txt", "suelto.txt"):
            self.assertEqual(before[path], after[path])
        self.assertEqual(before["otro.txt"], ("recognized", ("src_a",)))
        self.assertEqual(before["suelto.txt"], ("unknown", ()))

    # 11
    def test_11_path_without_reference_baseline_or_assignment_is_unchanged(self):
        profile, *_ = self._scenario()
        result = analyze_profile(profile)
        entry = self._entry(result, "suelto.txt")
        self.assertEqual(entry.membership.state, MembershipState.UNKNOWN)
        self.assertFalse(entry.is_unassigned_new)
        self.assertEqual(self._row_sources(result, "suelto.txt"), set())

    # 12
    def test_12_removing_assignment_restores_shared_and_keeps_baseline(self):
        profile, work, ref_a, ref_b, baseline_a, baseline_b = self._scenario()
        profile.assign_path("documento.txt", "src_b")
        self.assertTrue(profile.unassign_path("documento.txt"))
        self.assertEqual(profile.assignments, {})
        entry = self._entry(analyze_profile(profile), "documento.txt")
        # La reclamación histórica reaparece: vuelve a SHARED hasta que se
        # asigne de nuevo explícitamente. La baseline no se toca.
        self.assertEqual(entry.membership.state, MembershipState.SHARED)
        self.assertEqual(entry.membership.source_ids, ("src_a", "src_b"))
        self.assertEqual(profile.sources[0].baseline, baseline_a)
        self.assertEqual(profile.sources[1].baseline, baseline_b)

    # Cobertura del flujo GUI que hace posible la transferencia explícita.
    def test_13_shared_entry_can_be_assigned_from_review_page(self):
        window, profile, ref_a, ref_b, baseline_a, baseline_b = (
            self._persisted_window()
        )
        page = window._profile_admin_pages["indeterminados"]
        item = self._item_for_path(page, "documento.txt")
        self.assertIsNotNone(item)
        menu = page.context_menu_for(item)
        assign = next(
            (action for action in menu.actions() if action.text() == "Asignar a"),
            None,
        )
        self.assertIsNotNone(assign)
        self.assertIsNotNone(assign.menu())
        self.assertEqual(
            [action.text() for action in assign.menu().actions()],
            ["A", "B"],
        )
        assign.menu().actions()[1].trigger()
        menu.deleteLater()
        self.assertEqual(
            load_profile(profile.id).assignments,
            {"documento.txt": "src_b"},
        )
        entry = self._entry(window.profile_analysis, "documento.txt")
        self.assertEqual(entry.membership.state, MembershipState.RECOGNIZED)
        self.assertEqual(entry.membership.source_ids, ("src_b",))
        self.assertNotIn(
            "documento.txt",
            {row.path for row in window.profile_analysis.rows_by_source["src_a"]},
        )
        self.assertEqual(_read(ref_b, "documento.txt"), "doc-b")


if __name__ == "__main__":
    unittest.main()
