"""GUI regressions for physical absence styling and Home copy selection."""
import hashlib
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.gui.theme import semantic
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, axis_a, axis_b="untracked", destination="principal",
         owner="núcleo", incidences=()):
    return Row(path, owner, destination, axis_a, axis_b, list(incidences))


def _hash(path):
    with open(path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()


class HomeCopyAndAbsenceTests(unittest.TestCase):
    def setUp(self):
        self.settings = QSettings("Gipler", "Gipler")
        self.old_repository = self.settings.value("inicio/repositorio")
        self.old_view = self.settings.value("inicio/vista")
        self.settings.setValue("inicio/repositorio", "principal")
        self.settings.setValue("inicio/vista", "relevantes")
        self.settings.sync()
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "dev")
        self.principal = os.path.join(root, "principal")
        self.addons = os.path.join(root, "addons")
        for directory in (self.dev, self.principal, self.addons):
            os.makedirs(directory)
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.close()
        self.tmp.cleanup()
        if self.old_repository is None:
            self.settings.remove("inicio/repositorio")
        else:
            self.settings.setValue("inicio/repositorio", self.old_repository)
        if self.old_view is None:
            self.settings.remove("inicio/vista")
        else:
            self.settings.setValue("inicio/vista", self.old_view)
        self.settings.sync()

    def _write(self, root, path, text):
        full = os.path.join(root, *path.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as file:
            file.write(text)
        return full

    def _window(self, rows, snapshot=None):
        self.window = GiplerWindow(
            rows=rows,
            meta={
                "dev": self.dev,
                "principal": self.principal,
                "addons": self.addons,
            },
            snapshot=snapshot or {"dev": {}, "repos": {}},
        )
        return self.window

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
            from PySide6.QtCore import QModelIndex
            return QModelIndex()

        return walk(__import__("PySide6.QtCore", fromlist=["QModelIndex"]).QModelIndex())

    def test_strikeout_tracks_physical_absence_without_changing_color(self):
        rows = [
            _row("dev-only.txt", "new_in_dev"),
            _row("repo-only.txt", "missing_in_dev", "tracked_clean"),
            _row("both/missing.txt", "missing_in_dev", "tracked_clean"),
        ]
        self._write(self.dev, "dev-only.txt", "dev")
        self._write(self.principal, "repo-only.txt", "repo")
        window = self._window(rows)

        for proxy in (window.proxy, window.repo_proxy):
            for path, should_strike in (
                ("dev-only.txt", proxy is window.repo_proxy),
                ("repo-only.txt", proxy is window.proxy),
                ("both/missing.txt", True),
            ):
                index = self._proxy_index(proxy, path)
                self.assertTrue(index.isValid(), path)
                font = proxy.data(index, Qt.FontRole)
                self.assertEqual(bool(font and font.strikeOut()), should_strike, path)
        repo_dev_index = self._proxy_index(window.proxy, "repo-only.txt")
        self.assertEqual(
            window.proxy.data(repo_dev_index, Qt.ForegroundRole).name().lower(),
            semantic("oscuro", "missing_in_dev").lower(),
        )
        directory_index = self._proxy_index(window.proxy, "both")
        self.assertTrue(directory_index.isValid())
        self.assertIsNone(window.proxy.data(directory_index, Qt.FontRole))

    def test_home_checkboxes_share_selection_and_survive_tab_changes(self):
        dev_path = self._write(self.dev, "copy-me.txt", "new")
        addon_dev = self._write(self.dev, "addon/copy-me.txt", "addon")
        rows = [
            _row("copy-me.txt", "new_in_dev"),
            _row("addon/copy-me.txt", "new_in_dev", destination="addons"),
        ]
        snapshot = {
            "dev": {
                "copy-me.txt": _hash(dev_path),
                "addon/copy-me.txt": _hash(addon_dev),
            },
            "repos": {"principal": {}, "addons": {}},
        }
        window = self._window(rows, snapshot)
        panel = window.inicio_panel
        item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "copy-me.txt"
        )
        self.assertTrue(item.flags() & Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        key = ("principal", "copy-me.txt")
        self.assertIn(key, window.selection_ctrl)

        index = self._proxy_index(window.proxy, "copy-me.txt")
        self.assertEqual(window.tree_model.data(
            window.proxy.mapToSource(index), Qt.CheckStateRole
        ), Qt.Checked)
        window.set_destination("addons")
        self.assertIn(key, window.selection_ctrl)
        addon_tree_index = self._proxy_index(window.proxy, "addon/copy-me.txt")
        window.tree_model.setData(
            window.proxy.mapToSource(addon_tree_index),
            Qt.Checked,
            Qt.CheckStateRole,
        )
        self.assertIn(("addons", "addon/copy-me.txt"), window.selection_ctrl)
        panel.repository_selector.setCurrentIndex(
            panel.repository_selector.findData("addons")
        )
        addon_item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "addon/copy-me.txt"
        )
        window.tree_model.setData(
            window.proxy.mapToSource(addon_tree_index),
            Qt.Unchecked,
            Qt.CheckStateRole,
        )
        self.assertNotIn(("addons", "addon/copy-me.txt"), window.selection_ctrl)
        self.assertEqual(addon_item.checkState(), Qt.Unchecked)
        addon_item.setCheckState(Qt.Checked)
        addon_key = ("addons", "addon/copy-me.txt")
        self.assertIn(addon_key, window.selection_ctrl)
        self.assertEqual(addon_item.checkState(), Qt.Checked)

        window.set_destination("principal")
        panel.repository_selector.setCurrentIndex(
            panel.repository_selector.findData("principal")
        )
        item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "copy-me.txt"
        )
        item.setCheckState(Qt.Unchecked)
        self.assertNotIn(key, window.selection_ctrl)
        self.assertIn(addon_key, window.selection_ctrl)

    def test_home_checkboxes_follow_build_operations_eligibility(self):
        ready = self._write(self.dev, "ready.txt", "ready")
        ignored = self._write(self.dev, "ignored.txt", "ignored")
        excluded = self._write(self.dev, "excluded.txt", "excluded")
        identical_dev = self._write(self.dev, "identical.txt", "same")
        identical_repo = self._write(self.principal, "identical.txt", "same")
        local_dev = self._write(self.dev, "local.txt", "dev")
        local_repo = self._write(self.principal, "local.txt", "repo")
        absent_repo = self._write(self.principal, "absent.txt", "repo only")
        rows = [
            _row("ready.txt", "new_in_dev"),
            _row("ignored.txt", "new_in_dev", "ignored"),
            _row("excluded.txt", "new_in_dev", incidences=("excluded",)),
            _row("absent.txt", "missing_in_dev", "tracked_clean"),
            _row("identical.txt", "identical", "tracked_clean"),
            _row("local.txt", "modified_in_dev", "tracked_modified"),
            _row("unknown.txt", "new_in_dev", destination="sin determinar"),
        ]
        snapshot = {
            "dev": {
                "ready.txt": _hash(ready),
                "ignored.txt": _hash(ignored),
                "excluded.txt": _hash(excluded),
                "identical.txt": _hash(identical_dev),
                "local.txt": _hash(local_dev),
            },
            "repos": {
                "principal": {
                    "identical.txt": _hash(identical_repo),
                    "local.txt": _hash(local_repo),
                    "absent.txt": _hash(absent_repo),
                },
                "addons": {},
            },
        }
        window = self._window(rows, snapshot)
        self.assertEqual(
            window._eligible_copy_keys,
            {("principal", "ready.txt")},
        )
        self.assertNotIn(("principal", "ignored.txt"), window._eligible_copy_keys)
        self.assertNotIn(("principal", "absent.txt"), window._eligible_copy_keys)
        self.assertNotIn(("principal", "identical.txt"), window._eligible_copy_keys)
        self.assertNotIn(("principal", "local.txt"), window._eligible_copy_keys)
        self.assertNotIn(("sin determinar", "unknown.txt"), window._eligible_copy_keys)

        window.selection_ctrl.add(("principal", "ready.txt"))
        ops = window.prepare_operations(show_dialog=False)
        self.assertEqual([op.status for op in ops], ["copiable"])
        self.assertEqual(window.inicio_panel.btn_execute.text(), "Ejecutar copia (1)")
        self.assertTrue(window.inicio_panel.btn_execute.isEnabled())
        cached = list(window.ops_cache)
        window._show_compare("principal")
        window._show_inicio()
        self.assertEqual(window.ops_cache, cached)
        panel = window.inicio_panel
        ready_item = next(
            panel.list.item(i)
            for i in range(panel.list.count())
            if panel.list.item(i).data(Qt.UserRole).path == "ready.txt"
        )
        ready_item.setCheckState(Qt.Unchecked)
        self.assertEqual(window.ops_cache, [])
        self.assertEqual(window.inicio_panel.btn_execute.text(), "Ejecutar copia (0)")
        self.assertFalse(window.inicio_panel.btn_execute.isEnabled())


if __name__ == "__main__":
    unittest.main()
