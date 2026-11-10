"""Orden del árbol y expansión automática en exploradores GUI."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtCore import QModelIndex, Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, axis_a="identical", destination="principal", incidences=()):
    return Row(path, "núcleo", destination, axis_a, "tracked_clean", list(incidences))


class TreeOrderingAndExpansionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _row("root-z.txt"),
            _row("z-folder/z-file.txt"),
            _row("adir/quiet.txt"),
            _row("quiet-folder/only.txt"),
            _row("z-folder/a-folder/new.txt", "new_in_dev"),
            _row("adir/changed.txt", "modified_in_dev"),
            _row("m-folder/warning.txt", incidences=("shared_file",)),
            Row("x-folder/ambiguous.txt", "sin determinar", "principal",
                "identical", "tracked_clean", []),
            _row("addons/changed.txt", "modified_in_dev", "addons"),
            _row("addons/quiet/nothing.txt", destination="addons"),
            _row("root-a.txt"),
        ]
        self.window = GiplerWindow(
            rows=self.rows,
            meta={"dev": "", "principal": "", "addons": ""},
        )
        self.window.resize(1000, 700)
        self.window.show()
        app.processEvents()

    def tearDown(self):
        self.window.close()

    @staticmethod
    def _index_for_path(proxy, path):
        found = QModelIndex()

        def walk(parent):
            nonlocal found
            for position in range(proxy.rowCount(parent)):
                index = proxy.index(position, 0, parent)
                if index.data(Qt.UserRole + 1) == path:
                    found = index
                    return True
                if walk(index):
                    return True
            return False

        walk(QModelIndex())
        return found

    @staticmethod
    def _names(proxy, parent=QModelIndex()):
        return [
            proxy.index(position, 0, parent).data()
            for position in range(proxy.rowCount(parent))
        ]

    def _assert_expanded(self, proxy, tree, path, expected=True):
        index = self._index_for_path(proxy, path)
        self.assertTrue(index.isValid(), path)
        self.assertIs(index.model(), proxy)
        self.assertEqual(tree.isExpanded(index), expected, path)

    def test_directories_precede_files_and_sort_recursively(self):
        proxy = self.window.proxy
        self.assertEqual(
            self._names(proxy),
            [
                "adir", "m-folder", "quiet-folder", "x-folder", "z-folder",
                "root-a.txt", "root-z.txt",
            ],
        )
        z_folder = self._index_for_path(proxy, "z-folder")
        self.assertEqual(self._names(proxy, z_folder), ["a-folder", "z-file.txt"])
        a_folder = self._index_for_path(proxy, "z-folder/a-folder")
        self.assertEqual(self._names(proxy, a_folder), ["new.txt"])

    def test_relevant_rows_expand_ancestors_in_both_proxies(self):
        for proxy, tree in (
            (self.window.proxy, self.window.dev_panel.tree),
            (self.window.repo_proxy, self.window.dest_panel.tree),
        ):
            for path in (
                "z-folder", "z-folder/a-folder", "adir", "m-folder", "x-folder",
            ):
                self._assert_expanded(proxy, tree, path)

    def test_irrelevant_directories_remain_collapsed(self):
        for proxy, tree in (
            (self.window.proxy, self.window.dev_panel.tree),
            (self.window.repo_proxy, self.window.dest_panel.tree),
        ):
            self._assert_expanded(proxy, tree, "quiet-folder", False)

    def test_switching_destinations_refreshes_expansion(self):
        self.window.set_destination("addons")
        app.processEvents()
        self._assert_expanded(
            self.window.proxy, self.window.dev_panel.tree, "addons"
        )
        self._assert_expanded(
            self.window.repo_proxy, self.window.dest_panel.tree, "addons"
        )
        self.window.set_destination("principal")
        app.processEvents()
        for proxy, tree in (
            (self.window.proxy, self.window.dev_panel.tree),
            (self.window.repo_proxy, self.window.dest_panel.tree),
        ):
            self._assert_expanded(proxy, tree, "z-folder")
            self._assert_expanded(proxy, tree, "m-folder")

    def test_active_filters_expand_only_visible_relevant_rows_without_qt_warnings(self):
        messages = []
        previous_handler = qInstallMessageHandler(
            lambda _kind, _context, message: messages.append(message)
        )
        try:
            for tree, proxy in (
                (self.window.dev_panel.tree, self.window.proxy),
                (self.window.dest_panel.tree, self.window.repo_proxy),
            ):
                index = self._index_for_path(proxy, "adir")
                tree.collapse(index)
            self.window.axis_a_box.setCurrentText("new_in_dev")
            app.processEvents()
            for proxy, tree in (
                (self.window.proxy, self.window.dev_panel.tree),
                (self.window.repo_proxy, self.window.dest_panel.tree),
            ):
                self._assert_expanded(proxy, tree, "z-folder")
                self._assert_expanded(proxy, tree, "adir", False)
            self.window.axis_a_box.setCurrentText("todos")
            app.processEvents()
        finally:
            qInstallMessageHandler(previous_handler)
        self.assertFalse(any("different model" in message.lower() for message in messages))
        self.assertFalse(any("invalid" in message.lower() and "index" in message.lower() for message in messages))

    def test_reanalysis_restores_relevant_expansion(self):
        info = {
            "meta": {"dev": "", "principal": "", "addons": ""},
            "warnings": [],
            "snapshot": {"dev": {}, "repos": {}},
        }
        with patch("gipler.analysis.analyze", return_value=("", self.rows, info)):
            self.window.reanalyze()
        for proxy, tree in (
            (self.window.proxy, self.window.dev_panel.tree),
            (self.window.repo_proxy, self.window.dest_panel.tree),
        ):
            self._assert_expanded(proxy, tree, "z-folder/a-folder")


if __name__ == "__main__":
    unittest.main()
