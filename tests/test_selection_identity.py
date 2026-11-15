"""P0-9: identidad canónica de selección compartida por Inicio, árbol, TUI y páginas."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.gui.profile_window import ProfileListPage
from gipler.profile import (
    Profile,
    Source,
    create_profile,
    load_profile,
    save_profile,
)
from gipler.profile_analysis import analyze_profile
from gipler.report import Row
from gipler.selection import row_ref_for, selection_key_for
from gipler.tui import ProfileState
from .helpers import make_profile_window

APP = QApplication.instance() or QApplication([])


class SelectionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        self.windows = []

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        self.home.cleanup()

    def tearDown(self):
        for window in self.windows:
            window.close()

    @staticmethod
    def _write(root, path, content):
        full = os.path.join(root, *path.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as file:
            file.write(content)

    def _profile(self, name, work_files, source_specs):
        work = os.path.join(self.base, f"work-{name}")
        os.makedirs(work, exist_ok=True)
        for path, content in work_files.items():
            self._write(work, path, content)
        profile = create_profile(name, work)
        profile.sources = []
        roots = {}
        for spec in source_specs:
            source_id = spec["id"]
            root = os.path.join(self.base, f"root-{name}-{source_id}")
            dest = spec.get("dest")
            if dest is None:
                dest = os.path.join(self.base, f"dest-{name}-{source_id}")
            os.makedirs(root, exist_ok=True)
            os.makedirs(dest, exist_ok=True)
            for path, content in spec.get("files", {}).items():
                self._write(root, path, content)
            for path, content in spec.get("dest_files", {}).items():
                self._write(dest, path, content)
            profile.sources.append(
                Source(
                    id=source_id,
                    name=spec.get("name", source_id),
                    root=root,
                    order=spec.get("order", len(profile.sources)),
                    acts_as_recognizer=spec.get("recognizer", True),
                    acts_as_destination=spec.get("destination", False),
                    sync_enabled=spec.get("sync", True),
                    sync_destination=dest,
                    destination_source_id=spec.get("maps_to", ""),
                )
            )
            roots[source_id] = (root, dest)
        save_profile(profile)
        return load_profile(profile.id), roots

    def _window(self, profile):
        window = GiplerWindow(profile=profile)
        self.windows.append(window)
        return window

    @staticmethod
    def _tree_index(window, path):
        def walk(parent=QModelIndex()):
            for row in range(window.tree_model.rowCount(parent)):
                index = window.tree_model.index(row, 0, parent)
                node = window.tree_model.node_at(index)
                if node.path == path:
                    return index
                found = walk(index)
                if found.isValid():
                    return found
            return QModelIndex()

        return walk()

    @staticmethod
    def _home_item(window, path, destination=None):
        panel = window.inicio_panel
        for index in range(panel.list.count()):
            item = panel.list.item(index)
            row = item.data(Qt.UserRole)
            if row is None or row.path != path:
                continue
            if destination is None or row.destination == destination:
                return item
        return None

    def _mapped_profile(self):
        return self._profile(
            "mapped",
            {"doc.txt": "dev"},
            [
                {
                    "id": "src_ref",
                    "name": "Ref",
                    "files": {"doc.txt": "base"},
                    "maps_to": "src_dst",
                    "destination": False,
                },
                {
                    "id": "src_dst",
                    "name": "Dest",
                    "recognizer": False,
                    "destination": True,
                },
            ],
        )

    def test_mapped_source_home_and_tree_sync_bidirectionally(self):
        profile, _roots = self._mapped_profile()
        window = self._window(profile)
        key = ("src_dst", "doc.txt")

        self.assertEqual(window._destination, "src_ref")
        self.assertEqual(window._eligible_copy_keys, {key})
        home = self._home_item(window, "doc.txt", "src_ref")
        tree = self._tree_index(window, "doc.txt")
        self.assertIsNotNone(home)
        self.assertTrue(home.flags() & Qt.ItemIsUserCheckable)
        self.assertTrue(window.tree_model.flags(tree) & Qt.ItemIsUserCheckable)

        home.setCheckState(Qt.Checked)
        self.assertEqual(window.selection_ctrl.keys, {key})
        self.assertEqual(
            window.tree_model.data(tree, Qt.CheckStateRole), Qt.Checked
        )
        self.assertEqual(
            [op.destination for op in window.prepare_operations()], ["src_dst"]
        )

        home.setCheckState(Qt.Unchecked)
        self.assertEqual(window.selection_ctrl.keys, set())
        self.assertEqual(
            window.tree_model.data(tree, Qt.CheckStateRole), Qt.Unchecked
        )

        window.tree_model.setData(tree, Qt.Checked, Qt.CheckStateRole)
        self.assertEqual(window.selection_ctrl.keys, {key})
        self.assertEqual(home.checkState(), Qt.Checked)

    def test_same_path_distinct_destinations_are_independent(self):
        rows = [
            Row(
                "shared.txt", "núcleo", "src_a", "new_in_dev", "untracked", [],
                selection_key=("src_a", "shared.txt"),
            ),
            Row(
                "shared.txt", "núcleo", "src_b", "new_in_dev", "untracked", [],
                selection_key=("src_b", "shared.txt"),
            ),
        ]
        window, patcher = make_profile_window(
            self.base,
            rows,
            sources=[
                {"id": "src_a", "name": "A"},
                {"id": "src_b", "name": "B"},
            ],
            work_files={"shared.txt": "dev"},
        )
        self.windows.append(window)
        self.addCleanup(patcher.stop)
        key_a = ("src_a", "shared.txt")
        key_b = ("src_b", "shared.txt")
        self.assertEqual(window._eligible_copy_keys, {key_a, key_b})

        window.set_destination("src_a")
        home_a = self._home_item(window, "shared.txt", "src_a")
        tree_a = self._tree_index(window, "shared.txt")
        home_a.setCheckState(Qt.Checked)
        self.assertEqual(window.selection_ctrl.keys, {key_a})
        self.assertEqual(
            window.tree_model.data(tree_a, Qt.CheckStateRole), Qt.Checked
        )

        window.set_destination("src_b")
        tree_b = self._tree_index(window, "shared.txt")
        self.assertEqual(
            window.tree_model.data(tree_b, Qt.CheckStateRole), Qt.Unchecked
        )
        window.tree_model.setData(tree_b, Qt.Checked, Qt.CheckStateRole)
        self.assertEqual(window.selection_ctrl.keys, {key_a, key_b})
        self.assertEqual(
            {op.destination for op in window.prepare_operations()},
            {"src_a", "src_b"},
        )

    def test_same_path_same_target_is_one_operation(self):
        key = ("src_dst", "shared.txt")
        rows = [
            Row(
                "shared.txt", "núcleo", "src_a", "new_in_dev", "untracked", [],
                selection_key=key,
            ),
            Row(
                "shared.txt", "núcleo", "src_b", "new_in_dev", "untracked", [],
                selection_key=key,
            ),
            Row(
                "shared.txt", "núcleo", "src_dst", "new_in_dev", "untracked", [],
                selection_key=key,
            ),
        ]
        window, patcher = make_profile_window(
            self.base,
            rows,
            sources=[
                {"id": "src_a", "name": "A"},
                {"id": "src_b", "name": "B"},
                {"id": "src_dst", "name": "Dest"},
            ],
            work_files={"shared.txt": "dev"},
        )
        self.windows.append(window)
        self.addCleanup(patcher.stop)
        self.assertEqual(window._eligible_copy_keys, {key})

        window.set_destination("src_a")
        home = self._home_item(window, "shared.txt", "src_a")
        self.assertTrue(home.flags() & Qt.ItemIsUserCheckable)
        home.setCheckState(Qt.Checked)
        self.assertEqual(window.selection_ctrl.keys, {key})

        window.set_destination("src_b")
        tree_b = self._tree_index(window, "shared.txt")
        self.assertEqual(
            window.tree_model.data(tree_b, Qt.CheckStateRole), Qt.Checked
        )
        operations = window.prepare_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].destination, "src_dst")

    def test_selection_survives_tab_repository_and_filter_changes(self):
        profile, _roots = self._mapped_profile()
        window = self._window(profile)
        key = ("src_dst", "doc.txt")
        window.selection_ctrl.keys.add(key)

        window.set_destination("src_dst")
        window.set_destination("src_ref")
        window.inicio_panel.repository_selector.setCurrentIndex(
            window.inicio_panel.repository_selector.findData("src_ref")
        )
        window.search_edit.setText("doc")
        window.apply_filters()
        self.assertEqual(window.selection_ctrl.keys, {key})
        self.assertEqual(
            window.tree_model.data(self._tree_index(window, "doc.txt"), Qt.CheckStateRole),
            Qt.Checked,
        )

    def test_rows_without_selection_key_are_not_selectable(self):
        rows = [Row("x.txt", "núcleo", "principal", "new_in_dev", "untracked", [])]
        window, patcher = make_profile_window(
            self.base,
            rows,
            sources=[{"id": "principal", "name": "Principal"}],
            work_files={"x.txt": "x"},
            derive_selection_keys=False,
        )
        self.windows.append(window)
        self.addCleanup(patcher.stop)

        home = self._home_item(window, "x.txt", "principal")
        tree = self._tree_index(window, "x.txt")
        self.assertIsNotNone(home)
        self.assertFalse(home.flags() & Qt.ItemIsUserCheckable)
        self.assertFalse(window.tree_model.flags(tree) & Qt.ItemIsUserCheckable)
        self.assertFalse(
            window.tree_model.setData(tree, Qt.Checked, Qt.CheckStateRole)
        )
        self.assertEqual(window.selection_ctrl.keys, set())
        self.assertIsNone(selection_key_for(rows[0]))
        self.assertEqual(row_ref_for(rows[0]), ("principal", "x.txt"))

    def test_reanalysis_preserves_and_prunes_selection(self):
        profile, _roots = self._profile(
            "reanalysis",
            {"keep.txt": "keep", "drop.txt": "drop"},
            [
                {
                    "id": "src_all",
                    "files": {"keep.txt": "keep", "drop.txt": "drop"},
                    "destination": True,
                }
            ],
        )
        window = self._window(profile)
        key_keep = ("src_all", "keep.txt")
        key_drop = ("src_all", "drop.txt")
        window.selection_ctrl.keys.update({key_keep, key_drop})
        window.ops_cache = ["prepared"]
        window._prepared_token = object()
        window._authorized_token = window._prepared_token

        window.reanalyze()
        self.assertEqual(window.selection_ctrl.keys, {key_keep, key_drop})
        self.assertEqual(window.ops_cache, [])
        self.assertIsNone(window._prepared_token)
        self.assertIsNone(window._authorized_token)

        os.remove(os.path.join(profile.work_dir, "drop.txt"))
        window.reanalyze()
        self.assertEqual(window.selection_ctrl.keys, {key_keep})

    def test_reanalysis_drops_selection_when_eligibility_changes(self):
        profile, roots = self._profile(
            "eligibility",
            {"file.txt": "same"},
            [
                {
                    "id": "src_all",
                    "files": {"file.txt": "same"},
                    "destination": True,
                }
            ],
        )
        window = self._window(profile)
        key = ("src_all", "file.txt")
        window.selection_ctrl.keys.add(key)
        self.assertIn(key, window._eligible_copy_keys)

        dest_root = roots["src_all"][1]
        self._write(dest_root, "file.txt", "same")
        window.reanalyze()
        self.assertEqual(window.selection_ctrl.keys, set())
        self.assertNotIn(key, window._eligible_copy_keys)

    def test_reanalysis_does_not_autoselect_new_files(self):
        profile, _roots = self._profile(
            "new-file",
            {"old.txt": "old"},
            [
                {
                    "id": "src_all",
                    "files": {"old.txt": "old"},
                    "destination": True,
                }
            ],
        )
        window = self._window(profile)
        key = ("src_all", "old.txt")
        window.selection_ctrl.keys.add(key)
        self._write(profile.work_dir, "new.txt", "new")

        window.reanalyze()
        self.assertEqual(window.selection_ctrl.keys, {key})
        self.assertNotIn(("src_all", "new.txt"), window.selection_ctrl.keys)

    def test_exclude_prunes_only_affected_and_restore_does_not_select(self):
        profile, _roots = self._profile(
            "exclude",
            {"a.txt": "a", "b.txt": "b"},
            [
                {
                    "id": "src_all",
                    "files": {"a.txt": "a", "b.txt": "b"},
                    "destination": True,
                }
            ],
        )
        window = self._window(profile)
        key_a = ("src_all", "a.txt")
        key_b = ("src_all", "b.txt")
        window.selection_ctrl.keys.update({key_a, key_b})

        window.exclude_path("a.txt", False)
        self.assertEqual(window.selection_ctrl.keys, {key_b})
        self.assertNotIn(
            "a.txt", {row.path for row in window.rows}
        )

        excluded = next(
            entry
            for entry in window.profile_analysis.excluded_entries
            if entry.path == "a.txt"
        )
        window._restore_profile_exclusion(excluded)
        self.assertEqual(window.selection_ctrl.keys, {key_b})
        self.assertIn("a.txt", {row.path for row in window.rows})

    def test_selection_is_independent_of_visual_row_order(self):
        rows = [
            Row("a.txt", "núcleo", "principal", "new_in_dev", "untracked", []),
            Row("b.txt", "núcleo", "principal", "new_in_dev", "untracked", []),
        ]
        window, patcher = make_profile_window(
            self.base,
            rows,
            sources=[{"id": "principal", "name": "Principal"}],
            work_files={"a.txt": "a", "b.txt": "b"},
        )
        self.windows.append(window)
        self.addCleanup(patcher.stop)
        key = ("principal", "a.txt")
        window.selection_ctrl.keys.add(key)

        window.tree_model.set_rows(list(reversed(window.rows)), window._destination)
        window.proxy.apply()
        window.repo_proxy.apply()
        window._update_summary()
        self.assertEqual(window.selection_ctrl.keys, {key})

    def test_profile_list_page_and_tui_use_the_same_key(self):
        profile, _roots = self._mapped_profile()
        analysis = analyze_profile(profile)
        key = ("src_dst", "doc.txt")

        page = ProfileListPage(
            analysis.entries,
            "sin entradas",
            eligible_keys={key},
        )
        self.addCleanup(page.deleteLater)
        items = [
            page.list.item(index)
            for index in range(page.list.count())
            if page.list.item(index).data(Qt.UserRole) is not None
        ]
        entry_item = next(
            item for item in items if item.data(Qt.UserRole).path == "doc.txt"
        )
        self.assertEqual(entry_item.data(Qt.UserRole + 1), key)
        page.sync_selection({key})
        self.assertEqual(entry_item.checkState(), Qt.Checked)

        state = ProfileState(profile, analysis)
        state.active_view = "source:src_ref"
        state.cursor = 0
        self.assertEqual(state.current().path, "doc.txt")
        state.toggle()
        self.assertEqual(state.selection, {key})
        state.toggle()
        self.assertEqual(state.selection, set())


if __name__ == "__main__":
    unittest.main()
