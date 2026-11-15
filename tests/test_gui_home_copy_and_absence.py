"""GUI regressions for physical absence styling and Home copy selection."""
import hashlib
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.theme import semantic
from gipler.report import Row
from .helpers import make_profile_window

app = QApplication.instance() or QApplication([])

SOURCES = [
    {"id": "principal", "name": "Principal"},
    {"id": "addons", "name": "Addons"},
]


def _row(path, axis_a, axis_b="untracked", destination="principal",
         owner="núcleo", incidences=()):
    return Row(path, owner, destination, axis_a, axis_b, list(incidences))


def _hash(path):
    with open(path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()


class HomeCopyAndAbsenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.principal = os.path.join(root, "principal")
        self.addons = os.path.join(root, "addons")
        for directory in (self.dev, self.principal, self.addons):
            os.makedirs(directory)
        self.window = None
        self.patcher = None

    def tearDown(self):
        if self.window is not None:
            self.window.close()
        if self.patcher is not None:
            self.patcher.stop()
        self.tmp.cleanup()

    def _write(self, root, path, text):
        full = os.path.join(root, *path.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as file:
            file.write(text)
        return full

    def _close(self):
        if self.window is not None:
            self.window.close()

    def _proxy_index(self, proxy, path):
        def walk(parent):
            for index in range(proxy.rowCount(parent)):
                current = proxy.index(index, 0, parent)
                node = self.window.tree_model.node_at(proxy.mapToSource(current))
                if node.path == path:
                    return current
                found = walk(current)
                if found.isValid():
                    return found
            return QModelIndex()

        return walk(QModelIndex())

    def test_strikeout_tracks_physical_absence_without_changing_color(self):
        rows = [
            _row("dev-only.txt", "new_in_dev"),
            _row("repo-only.txt", "missing_in_dev", "tracked_clean"),
            _row("both/missing.txt", "missing_in_dev", "tracked_clean"),
        ]
        self.window, self.patcher = make_profile_window(
            self.tmp.name,
            rows,
            sources=SOURCES,
            work_files={"dev-only.txt": "dev"},
            source_files={"principal": {"repo-only.txt": "repo"}},
            write_files=False,
        )

        for proxy in (self.window.proxy, self.window.repo_proxy):
            for path, should_strike in (
                ("dev-only.txt", proxy is self.window.repo_proxy),
                ("repo-only.txt", proxy is self.window.proxy),
                ("both/missing.txt", True),
            ):
                index = self._proxy_index(proxy, path)
                self.assertTrue(index.isValid(), path)
                font = proxy.data(index, Qt.FontRole)
                self.assertEqual(bool(font and font.strikeOut()), should_strike, path)
        repo_dev_index = self._proxy_index(self.window.proxy, "repo-only.txt")
        self.assertEqual(
            self.window.proxy.data(repo_dev_index, Qt.ForegroundRole).name().lower(),
            semantic("oscuro", "missing_in_dev").lower(),
        )
        directory_index = self._proxy_index(self.window.proxy, "both")
        self.assertTrue(directory_index.isValid())
        self.assertIsNone(self.window.proxy.data(directory_index, Qt.FontRole))

    def test_home_checkboxes_share_selection_and_survive_tab_changes(self):
        work_files = {"copy-me.txt": "new", "addon/copy-me.txt": "addon"}
        rows = [
            _row("copy-me.txt", "new_in_dev"),
            _row("addon/copy-me.txt", "new_in_dev", destination="addons"),
        ]
        self.window, self.patcher = make_profile_window(
            self.tmp.name, rows, sources=SOURCES, work_files=work_files
        )
        dev_root = self.window.profile.work_dir
        snapshot = {
            "dev": {
                "copy-me.txt": _hash(os.path.join(dev_root, "copy-me.txt")),
                "addon/copy-me.txt": _hash(os.path.join(dev_root, "addon", "copy-me.txt")),
            },
            "repos": {"principal": {}, "addons": {}},
        }
        self.window.snapshot = snapshot
        self.window._refresh_copy_eligibility()
        panel = self.window.inicio_panel
        item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "copy-me.txt"
        )
        self.assertTrue(item.flags() & Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        key = ("principal", "copy-me.txt")
        self.assertIn(key, self.window.selection_ctrl)

        index = self._proxy_index(self.window.proxy, "copy-me.txt")
        self.assertEqual(self.window.tree_model.data(
            self.window.proxy.mapToSource(index), Qt.CheckStateRole
        ), Qt.Checked)
        self.window.set_destination("addons")
        self.assertIn(key, self.window.selection_ctrl)
        addon_tree_index = self._proxy_index(self.window.proxy, "addon/copy-me.txt")
        self.window.tree_model.setData(
            self.window.proxy.mapToSource(addon_tree_index),
            Qt.Checked,
            Qt.CheckStateRole,
        )
        self.assertIn(("addons", "addon/copy-me.txt"), self.window.selection_ctrl)
        panel.repository_selector.setCurrentIndex(
            panel.repository_selector.findData("addons")
        )
        addon_item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "addon/copy-me.txt"
        )
        self.window.tree_model.setData(
            self.window.proxy.mapToSource(addon_tree_index),
            Qt.Unchecked,
            Qt.CheckStateRole,
        )
        self.assertNotIn(("addons", "addon/copy-me.txt"), self.window.selection_ctrl)
        self.assertEqual(addon_item.checkState(), Qt.Unchecked)
        addon_item.setCheckState(Qt.Checked)
        addon_key = ("addons", "addon/copy-me.txt")
        self.assertIn(addon_key, self.window.selection_ctrl)
        self.assertEqual(addon_item.checkState(), Qt.Checked)

        self.window.set_destination("principal")
        panel.repository_selector.setCurrentIndex(
            panel.repository_selector.findData("principal")
        )
        item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "copy-me.txt"
        )
        item.setCheckState(Qt.Unchecked)
        self.assertNotIn(key, self.window.selection_ctrl)
        self.assertIn(addon_key, self.window.selection_ctrl)

    def test_home_checkboxes_follow_build_operations_eligibility(self):
        work_files = {
            "ready.txt": "ready",
            "ignored.txt": "ignored",
            "excluded.txt": "excluded",
            "identical.txt": "same",
            "local.txt": "dev",
        }
        source_files = {
            "principal": {"identical.txt": "same", "local.txt": "repo", "absent.txt": "repo only"},
        }
        rows = [
            _row("ready.txt", "new_in_dev"),
            _row("ignored.txt", "new_in_dev", "ignored"),
            _row("excluded.txt", "new_in_dev", incidences=("excluded",)),
            _row("absent.txt", "missing_in_dev", "tracked_clean"),
            _row("identical.txt", "identical", "tracked_clean"),
            _row("local.txt", "modified_in_dev", "tracked_modified"),
            _row("unknown.txt", "new_in_dev", destination="sin determinar"),
        ]
        self.window, self.patcher = make_profile_window(
            self.tmp.name,
            rows,
            sources=SOURCES,
            work_files=work_files,
            source_files=source_files,
        )
        dev_root = self.window.profile.work_dir
        repo_root = self.window.meta["principal"]
        snapshot = {
            "dev": {
                "ready.txt": _hash(os.path.join(dev_root, "ready.txt")),
                "ignored.txt": _hash(os.path.join(dev_root, "ignored.txt")),
                "excluded.txt": _hash(os.path.join(dev_root, "excluded.txt")),
                "identical.txt": _hash(os.path.join(dev_root, "identical.txt")),
                "local.txt": _hash(os.path.join(dev_root, "local.txt")),
            },
            "repos": {
                "principal": {
                    "identical.txt": _hash(os.path.join(repo_root, "identical.txt")),
                    "local.txt": _hash(os.path.join(repo_root, "local.txt")),
                    "absent.txt": _hash(os.path.join(repo_root, "absent.txt")),
                },
                "addons": {},
            },
        }
        self.window.snapshot = snapshot
        self.window._refresh_copy_eligibility()
        self.assertEqual(
            self.window._eligible_copy_keys,
            {("principal", "ready.txt")},
        )
        self.assertNotIn(("principal", "ignored.txt"), self.window._eligible_copy_keys)
        self.assertNotIn(("principal", "absent.txt"), self.window._eligible_copy_keys)
        self.assertNotIn(("principal", "identical.txt"), self.window._eligible_copy_keys)
        self.assertNotIn(("principal", "local.txt"), self.window._eligible_copy_keys)
        self.assertNotIn(("sin determinar", "unknown.txt"), self.window._eligible_copy_keys)

        self.window.selection_ctrl.add(("principal", "ready.txt"))
        ops = self.window.prepare_operations(show_dialog=False)
        self.assertEqual([op.status for op in ops], ["copiable"])
        self.assertEqual(self.window.inicio_panel.btn_execute.text(), "Ejecutar copia (1)")
        self.assertTrue(self.window.inicio_panel.btn_execute.isEnabled())
        cached = list(self.window.ops_cache)
        self.window._show_compare("principal")
        self.window._show_inicio()
        self.assertEqual(self.window.ops_cache, cached)
        panel = self.window.inicio_panel
        ready_item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "ready.txt"
        )
        ready_item.setCheckState(Qt.Unchecked)
        self.assertEqual(self.window.ops_cache, [])
        self.assertEqual(self.window.inicio_panel.btn_execute.text(), "Ejecutar copia (0)")
        self.assertFalse(self.window.inicio_panel.btn_execute.isEnabled())


if __name__ == "__main__":
    unittest.main()
