"""Tests Fase 2 GUI (offscreen, experiencia sincronizada)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from gipler.gui.main_window import GiplerWindow
from gipler.gui.models.comparison_tree import ComparisonTreeModel
from gipler.gui.models.filter_model import FilterModel, visible_file_count
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, a, b, owner="núcleo", dest="principal", inc=()):
    return Row(path, owner, dest, a, b, list(inc))


ROWS = [
    _row("ifs/a/b/mod.sh", "modified_in_dev", "tracked_clean"),
    _row("ifs/a/only_dev.txt", "new_in_dev", "untracked"),
    _row("addons/Podcasts/images/img.11.png", "identical", "tracked_clean",
         owner="Podcasts", dest="principal", inc=["present_in_both_repos"]),
    _row("addons/Podcasts/debian/control", "missing_in_dev", "ignored"),
    _row("same.txt", "identical", "tracked_modified"),
]


class Phase2ModelTests(unittest.TestCase):
    def _window(self):
        w = GiplerWindow(rows=ROWS)
        return w

    def _get_proxy_index(self, w, path, proxy):
        # Localizar índice proxy cuyo path coincide.
        found = None
        def walk(pidx):
            nonlocal found
            for i in range(proxy.rowCount(pidx)):
                idx = proxy.index(i, 0, pidx)
                src_node = w.tree_model.node_at(proxy.mapToSource(idx))
                if src_node.path == path:
                    found = idx
                    return True
                if walk(idx):
                    return True
            return False
        walk(QModelIndex())
        return found

    def test_tree_hierarchy_and_missing(self):
        m = ComparisonTreeModel(ROWS, "principal")
        self.assertTrue(any(n.path == "ifs/a/b/mod.sh" for n in m.file_nodes()))
        self.assertEqual(len(m.file_nodes()), 5)
        names = [n.name for n in m.file_nodes()]
        self.assertIn("img.11.png", names)

    def test_synced_navigation_double_click(self):
        w = self._window()
        self.addCleanup(w.close)
        proxy = w.proxy
        idx = self._get_proxy_index(w, "ifs/a", proxy)
        w._on_double_clicked(idx)
        self.assertEqual(w.dev_panel.tree.rootIndex().data(0x0100 + 1), "ifs/a")
        self.assertEqual(w.dest_panel.tree.rootIndex().data(0x0100 + 1), "ifs/a")

    def test_filters_combined_and_counters(self):
        w = self._window()
        self.addCleanup(w.close)
        w.axis_a_box.setCurrentText("modified_in_dev")
        self.assertEqual(visible_file_count(w.proxy), 1)
        w.axis_a_box.setCurrentText("todos")
        w.axis_b_box.setCurrentText("tracked_modified")
        self.assertEqual(visible_file_count(w.proxy), 1)
        w.axis_b_box.setCurrentText("todos")
        w.incidences_box.setChecked(True)
        self.assertEqual(visible_file_count(w.proxy), 1)
        w.incidences_box.setChecked(False)
        w.search_edit.setText("mod.sh")
        self.assertEqual(visible_file_count(w.proxy), 1)

    def test_search_and_owner(self):
        w = self._window()
        self.addCleanup(w.close)
        w.search_edit.setText("img.11")
        self.assertEqual(visible_file_count(w.proxy), 1)

    def test_three_tabs_switch(self):
        w = self._window()
        self.addCleanup(w.close)
        for dest, expected_files in (("principal", 5), ("addons", 0), ("sin determinar", 0)):
            w.set_destination(dest)
            self.assertEqual(len(w.tree_model.file_nodes()), expected_files)
        w.set_destination("principal")

    def test_explorer_columns_keep_internal_states_across_destinations(self):
        w = self._window()
        self.addCleanup(w.close)
        w.resize(1440, 900)
        w._show_compare("principal")
        app.processEvents()
        self.assertEqual(w.dev_panel.tree.model().columnCount(), 3)
        self.assertEqual(w.dest_panel.tree.model().columnCount(), 3)
        self.assertTrue(w.dev_panel.tree.isColumnHidden(1))
        self.assertFalse(w.dev_panel.tree.isColumnHidden(0))
        self.assertFalse(w.dev_panel.tree.isColumnHidden(2))
        self.assertFalse(w.dest_panel.tree.isColumnHidden(1))
        self.assertGreater(
            w.dev_panel.tree.columnWidth(0),
            w.dest_panel.tree.columnWidth(0),
        )
        self.assertEqual(w.proxy.headerData(0, Qt.Horizontal), "Nombre")
        self.assertEqual(w.proxy.headerData(1, Qt.Horizontal), "Estado del destino")
        self.assertEqual(w.proxy.headerData(2, Qt.Horizontal), "Advertencias")
        self.assertEqual(w.repo_proxy.headerData(1, Qt.Horizontal), "Estado Git")

        for destination in ("principal", "addons", "sin determinar"):
            w.set_destination(destination)
            self.assertTrue(w.dev_panel.tree.isColumnHidden(1))
            self.assertFalse(w.dest_panel.tree.isColumnHidden(1))

        w.set_destination("principal")
        row = ROWS[0]
        proxy_index = self._get_proxy_index(w, row.path, w.proxy)
        source_index = w.proxy.mapToSource(proxy_index)
        dev_index = w.proxy.mapFromSource(source_index)
        repo_index = w.repo_proxy.mapFromSource(source_index)
        self.assertEqual(w.proxy.data(dev_index.siblingAtColumn(1)), row.axis_b)
        self.assertEqual(w.repo_proxy.data(repo_index.siblingAtColumn(1)), row.axis_b)
        self.assertEqual(w.tree_model.node_at(source_index).row.axis_a, row.axis_a)

    def test_empty_dir_shown_after_search(self):
        w = self._window()
        self.addCleanup(w.close)
        w.search_edit.setText("inexistente-xyz")
        self.assertEqual(visible_file_count(w.proxy), 0)
        # El directorio estructural existe aunque no haya archivos.
        self.assertTrue(w.tree_model.file_nodes())


if __name__ == "__main__":
    unittest.main()
