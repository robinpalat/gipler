"""Interacciones de inspección de archivos relevantes de Inicio."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from gipler.gui.comparison_window import ComparisonWindow
from gipler.gui.main_window import GiplerWindow
from gipler.report import Row

app = QApplication.instance() or QApplication([])


def _row(path, axis_a="modified_in_dev", axis_b="tracked_clean",
         destination="principal", incidences=()):
    return Row(path, "núcleo", destination, axis_a, axis_b, list(incidences))


class HomeInteractionsTests(unittest.TestCase):
    def setUp(self):
        self.settings = QSettings("Gipler", "Gipler")
        self.old_destination = self.settings.value("inicio/repositorio")
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
        self.rows = [
            _row("dirA/shared.txt"),
            _row("dirB/shared.txt", axis_a="new_in_dev"),
            _row("addon/plugin.py", destination="addons"),
            _row("addon/orphan.py", axis_a="missing_in_dev", destination="addons"),
            _row("only-dev.txt", axis_a="new_in_dev", axis_b="untracked"),
            _row("only-repo.txt", axis_a="missing_in_dev"),
            _row("uncertain.txt", axis_a="modified_in_dev", destination="sin determinar"),
        ]
        self._write(self.dev, "dirA/shared.txt", "dev A")
        self._write(self.principal, "dirA/shared.txt", "repo A")
        self._write(self.dev, "dirB/shared.txt", "dev B")
        self._write(self.dev, "addon/plugin.py", "addon dev")
        self._write(self.addons, "addon/plugin.py", "addon repo")
        self._write(self.addons, "addon/orphan.py", "orphan addon")
        self._write(self.dev, "only-dev.txt", "new")
        self._write(self.principal, "only-repo.txt", "orphan")
        self.window = GiplerWindow(
            rows=self.rows,
            meta={
                "dev": self.dev,
                "principal": self.principal,
                "addons": self.addons,
            },
            snapshot={"dev": {}, "repos": {}},
        )

    def tearDown(self):
        self.window.close()
        for child in self.window.findChildren(ComparisonWindow):
            child.close()
        self.tmp.cleanup()
        if self.old_destination is None:
            self.settings.remove("inicio/repositorio")
        else:
            self.settings.setValue("inicio/repositorio", self.old_destination)
        if self.old_view is None:
            self.settings.remove("inicio/vista")
        else:
            self.settings.setValue("inicio/vista", self.old_view)
        self.settings.sync()

    @staticmethod
    def _write(root, relative, contents):
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(contents)

    def _item_for(self, path, destination=None):
        for index in range(self.window.inicio_panel.list.count()):
            item = self.window.inicio_panel.list.item(index)
            row = item.data(Qt.UserRole)
            if row.path == path and (destination is None or row.destination == destination):
                return item
        self.fail(f"No se encontró {path} en Inicio")

    def test_click_selects_inspection_and_updates_full_metadata(self):
        panel = self.window.inicio_panel
        item = self._item_for("dirA/shared.txt")
        self.window.selection_ctrl.add(("principal", "copy-target.txt"))
        self.window.ops_cache = ["prepared"]
        QTest.mouseClick(
            panel.list.viewport(),
            Qt.LeftButton,
            pos=panel.list.visualItemRect(item).center(),
        )
        app.processEvents()

        text = panel.file_info.text()
        self.assertIn("Ruta relativa: dirA/shared.txt", text)
        self.assertIn("Estado A: modified_in_dev", text)
        self.assertIn("Estado B: tracked_clean", text)
        self.assertIn(os.path.join(self.dev, "dirA/shared.txt"), text)
        self.assertIn(os.path.join(self.principal, "dirA/shared.txt"), text)
        self.assertIn("tamaño=5", text)
        self.assertIn("permisos=", text)
        self.assertIn("sha256=", text)
        self.assertEqual(self.window.selection_ctrl.keys, {("principal", "copy-target.txt")})
        self.assertEqual(self.window.ops_cache, ["prepared"])
        self.assertIs(panel.list.currentItem(), item)

    def test_same_basename_keeps_distinct_row_and_metadata(self):
        panel = self.window.inicio_panel
        item = self._item_for("dirB/shared.txt")
        panel.list.setCurrentItem(item)
        self.assertIn(os.path.join(self.dev, "dirB/shared.txt"), panel.file_info.text())
        self.assertNotIn(os.path.join(self.principal, "dirA/shared.txt"), panel.file_info.text())
        self.assertIn("Existencia física — Dev: sí  |  Repositorio: no", panel.file_info.text())

    def test_context_menu_selection_and_explorer_action(self):
        selector = self.window.inicio_panel.repository_selector
        selector.setCurrentIndex(selector.findData("addons"))
        item = self._item_for("addon/orphan.py", "addons")
        menu = self.window.inicio_panel.context_menu_for(item)
        self.assertEqual(
            [action.text() for action in menu.actions()],
            ["Seleccionar", "Abrir en explorador", "Excluir"],
        )
        menu.actions()[0].trigger()
        self.assertIs(self.window.inicio_panel.list.currentItem(), item)
        with patch("PySide6.QtGui.QDesktopServices.openUrl", return_value=True) as open_url:
            menu.actions()[1].trigger()
        target_url = open_url.call_args.args[0]
        self.assertEqual(
            target_url.toLocalFile(),
            os.path.join(self.addons, "addon"),
        )

    def test_double_click_opens_existing_comparison_for_both_repositories(self):
        for path, destination, repo_root in (
            ("dirA/shared.txt", "principal", self.principal),
            ("addon/plugin.py", "addons", self.addons),
        ):
            selector = self.window.inicio_panel.repository_selector
            selector.setCurrentIndex(selector.findData(destination))
            item = self._item_for(path, destination)
            self.window.inicio_panel.list.itemDoubleClicked.emit(item)
            app.processEvents()
            opened = [
                child for child in self.window.findChildren(ComparisonWindow)
                if child.row.path == path
            ]
            self.assertTrue(opened)
            self.assertEqual(opened[-1].repo_root, repo_root)
            self.assertEqual(opened[-1].dev_root, self.dev)
            opened[-1].close()

    def test_comparison_without_counterpart(self):
        for row, repo_root, expected in (
            (_row("only-dev.txt", "new_in_dev", "untracked"), self.principal, "sin contraparte"),
            (_row("only-repo.txt", "missing_in_dev"), self.principal, "solo existe"),
        ):
            window = ComparisonWindow(row, self.dev, repo_root)
            text = " ".join(
                window.diff.left.item(index).text()
                for index in range(window.diff.left.count())
            )
            self.assertIn(expected, text)
            window.close()

    def test_exclude_uses_existing_persistence_and_refreshes_home(self):
        item = self._item_for("only-dev.txt")
        self.window.selection_ctrl.add(("principal", "only-dev.txt"))
        self.window.ops_cache = ["prepared"]
        ignore_file = os.path.join(self.tmp.name, "config", "ignore.toml")
        with patch("gipler.ignore.ignore_path", return_value=ignore_file):
            menu = self.window.inicio_panel.context_menu_for(item)
            menu.actions()[2].trigger()
            app.processEvents()

        self.assertFalse(any(row.path == "only-dev.txt" for row in self.window.rows))
        self.assertFalse(any(
            self.window.inicio_panel.list.item(index).text() == "only-dev.txt"
            for index in range(self.window.inicio_panel.list.count())
        ))
        self.assertEqual(self.window.selection_ctrl.keys, set())
        self.assertEqual(self.window.ops_cache, [])
        with open(ignore_file, encoding="utf-8") as file:
            self.assertIn("only-dev.txt", file.read())

    def test_relevance_filter_uses_analysis_states_and_incidences(self):
        relevant = [
            _row(".gitignore", "modified_in_dev"),
            _row("translations/messages.mo", "new_in_dev", "untracked"),
            _row("default/config.xml", "missing_in_dev"),
            _row("ignored/with_issue.xml", "identical", "ignored",
                 incidences=("external_dependency",)),
            _row("images/img.11.png", "identical", "tracked_clean",
                 incidences=("present_in_both_repos",)),
            _row("ambiguous.xml", "identical", "tracked_clean",
                 incidences=("ambiguous",)),
        ]
        irrelevant = [
            _row("identical.txt", "identical", "tracked_clean"),
            _row("ordinary.txt", "identical", "tracked_clean"),
            _row("ignored/no_issue.xml", "identical", "ignored"),
        ]
        panel = self.window.inicio_panel
        panel.update_from(relevant + irrelevant)
        paths = {
            panel.list.item(index).data(Qt.UserRole).path
            for index in range(panel.list.count())
        }
        self.assertEqual(paths, {
            ".gitignore",
            "translations/messages.mo",
            "default/config.xml",
            "images/img.11.png",
            "ambiguous.xml",
        })

    def test_repository_selector_scopes_items_and_persists(self):
        selector = self.window.inicio_panel.repository_selector
        self.assertEqual([selector.itemData(i) for i in range(selector.count())], ["principal", "addons"])
        self.assertEqual(self._visible_paths(), {
            "dirA/shared.txt", "dirB/shared.txt", "only-dev.txt", "only-repo.txt",
        })

        selector.setCurrentIndex(selector.findData("addons"))
        self.assertEqual(self._visible_paths(), {"addon/plugin.py", "addon/orphan.py"})
        self.assertEqual(
            self.settings.value("inicio/repositorio"),
            "addons",
        )
        self.assertEqual(self.window.inicio_panel.counters["nuevos"][1].text(), "Nuevos en Dev: 0")

        second = GiplerWindow(
            rows=self.rows,
            meta={"dev": self.dev, "principal": self.principal, "addons": self.addons},
        )
        try:
            self.assertEqual(second.inicio_panel.repository_selector.currentData(), "addons")
        finally:
            second.close()

    def test_four_view_modes_combine_with_both_repository_destinations(self):
        rows = [
            _row("shared/name.txt", "new_in_dev", "untracked", destination="principal"),
            _row("changed.txt", "modified_in_dev", "tracked_clean", destination="principal"),
            _row("missing.txt", "missing_in_dev", "tracked_clean", destination="principal"),
            _row("warning.txt", "identical", "tracked_modified", destination="principal"),
            _row("incident.txt", "identical", "tracked_clean", destination="principal", incidences=("ambiguous",)),
            _row("clean.txt", "identical", "tracked_clean", destination="principal"),
            _row("ignored.txt", "new_in_dev", "ignored", destination="principal"),
            _row("excluded.txt", "new_in_dev", "untracked", destination="principal", incidences=("excluded",)),
            _row("shared/name.txt", "modified_in_dev", "tracked_clean", destination="addons"),
            _row("addon-warning.txt", "identical", "tracked_modified", destination="addons"),
            _row("addon-incident.txt", "identical", "tracked_clean", destination="addons", incidences=("shared_file",)),
            _row("addon-clean.txt", "identical", "tracked_clean", destination="addons"),
        ]
        panel = self.window.inicio_panel
        panel.update_from(rows)
        expected = {
            "principal": {
                "relevantes": {"shared/name.txt", "changed.txt", "missing.txt", "incident.txt"},
                "advertencias": {"warning.txt"},
                "incidencias": {"incident.txt"},
                "todo": {"shared/name.txt", "changed.txt", "missing.txt", "warning.txt", "incident.txt", "clean.txt"},
            },
            "addons": {
                "relevantes": {"shared/name.txt", "addon-incident.txt"},
                "advertencias": {"addon-warning.txt"},
                "incidencias": {"addon-incident.txt"},
                "todo": {"shared/name.txt", "addon-warning.txt", "addon-incident.txt", "addon-clean.txt"},
            },
        }
        for destination, views in expected.items():
            panel.repository_selector.setCurrentIndex(
                panel.repository_selector.findData(destination)
            )
            for view, expected_paths in views.items():
                panel.view_selector.setCurrentIndex(panel.view_selector.findData(view))
                self.assertEqual(
                    self._visible_paths(),
                    expected_paths,
                    f"{destination}/{view}",
                )
                for index in range(panel.list.count()):
                    row = panel.list.item(index).data(Qt.UserRole)
                    self.assertEqual(row.destination, destination)

    def test_view_selector_is_accessible_and_persisted(self):
        panel = self.window.inicio_panel
        self.assertEqual(
            [panel.view_selector.itemData(index) for index in range(panel.view_selector.count())],
            ["relevantes", "advertencias", "incidencias", "todo"],
        )
        self.assertEqual(panel.repository_selector.accessibleName(), "Repositorio de Inicio")
        self.assertEqual(panel.view_selector.accessibleName(), "Tipo de vista de Inicio")
        panel.view_selector.setCurrentIndex(panel.view_selector.findData("todo"))
        self.assertEqual(self.settings.value("inicio/vista"), "todo")
        second = GiplerWindow(
            rows=self.rows,
            meta={"dev": self.dev, "principal": self.principal, "addons": self.addons},
        )
        try:
            self.assertEqual(second.inicio_panel.view_selector.currentData(), "todo")
        finally:
            second.close()

    def test_interactions_remain_available_in_each_view(self):
        rows = [
            _row("relevant.txt", "new_in_dev", "untracked"),
            _row("warning.txt", "identical", "tracked_modified"),
            _row("incident.txt", "identical", "tracked_clean", incidences=("ambiguous",)),
            _row("ordinary.txt", "identical", "tracked_clean"),
        ]
        panel = self.window.inicio_panel
        panel.update_from(rows)
        expected_paths = {
            "relevantes": "relevant.txt",
            "advertencias": "warning.txt",
            "incidencias": "incident.txt",
            "todo": "ordinary.txt",
        }
        selection = {("principal", "copy-target.txt")}
        self.window.selection_ctrl.keys.clear()
        self.window.selection_ctrl.keys.update(selection)
        self.window.ops_cache = ["prepared"]

        for view, path in expected_paths.items():
            panel.view_selector.setCurrentIndex(panel.view_selector.findData(view))
            item = self._item_for(path, "principal")
            panel.list.setCurrentItem(item)
            self.assertIn(path, panel.file_info.text())
            menu = panel.context_menu_for(item)
            self.assertEqual(
                [action.text() for action in menu.actions()],
                ["Seleccionar", "Abrir en explorador", "Excluir"],
            )
            opened = QSignalSpy(panel.open_requested)
            panel.list.itemDoubleClicked.emit(item)
            self.assertEqual(opened.count(), 1)

        self.assertEqual(self.window.selection_ctrl.keys, selection)
        self.assertEqual(self.window.ops_cache, ["prepared"])

    def _visible_paths(self):
        panel = self.window.inicio_panel
        return {panel.list.item(i).text() for i in range(panel.list.count())}

    def test_ignored_excluded_rows_do_not_appear_or_count_as_attention(self):
        rows = [
            _row("ignored/issue.txt", "modified_in_dev", "ignored",
                 incidences=("external_dependency",)),
            _row("local-excluded.txt", "new_in_dev", "untracked",
                 incidences=("excluded",)),
            _row("parent/child.txt", "new_in_dev", "untracked"),
            _row("keep.txt", "modified_in_dev", "tracked_clean"),
        ]
        from gipler import ignore
        with patch.object(ignore, "load_patterns", return_value=["parent/"]):
            self.window.inicio_panel.update_from(rows)

        self.assertEqual(self._visible_paths(), {"keep.txt"})
        self.assertEqual(
            self.window.inicio_panel.counters["advertencias"][1].text(),
            "Con advertencias/incidencias: 0",
        )
        self.assertEqual(
            self.window.inicio_panel.counters["nuevos"][1].text(),
            "Nuevos en Dev: 0",
        )

    def test_excluded_rows_and_directory_descendants_are_not_prepared(self):
        from gipler import copy_engine, ignore

        rows = [
            _row("private/child.txt", "new_in_dev", "untracked"),
            _row("manifest-excluded.txt", "new_in_dev", "untracked",
                 incidences=("excluded",)),
            _row("keep.txt", "new_in_dev", "untracked"),
        ]
        self.window.rows = rows
        self.window.selection_ctrl.keys.clear()
        self.window.selection_ctrl.keys.update(
            ("principal", row.path) for row in rows
        )
        captured = {}

        def capture_selection(_rows, selection, *_args):
            captured["selection"] = set(selection)
            return []

        with patch.object(ignore, "load_patterns", return_value=["private/"]), \
             patch.object(copy_engine, "build_operations", side_effect=capture_selection):
            self.assertEqual(self.window.prepare_operations(), [])

        self.assertEqual(captured["selection"], {("principal", "keep.txt")})

    def test_blocked_prepared_operation_is_relevant(self):
        blocked = _row("blocked.txt", "identical", "tracked_clean")
        operation = SimpleNamespace(
            destination=blocked.destination,
            path=blocked.path,
            status="bloqueada",
        )
        panel = self.window.inicio_panel
        panel.update_from([blocked], [operation])
        self.assertEqual(panel.list.count(), 1)
        self.assertIs(panel.list.item(0).data(Qt.UserRole), blocked)


if __name__ == "__main__":
    unittest.main()
