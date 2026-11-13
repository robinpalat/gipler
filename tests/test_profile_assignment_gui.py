"""GUI: asignación de archivos nuevos sin referencia (Inicio e Indeterminados)."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy

from gipler.gui.main_window import GiplerWindow
from gipler.profile import (
    capture_source_baseline,
    create_profile,
    load_profile,
    save_profile,
    Source,
)

APP = QApplication.instance() or QApplication([])


class NewFileAssignmentGuiTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.ref_a = os.path.join(self.tmp.name, "ref-a")
        self.ref_b = os.path.join(self.tmp.name, "ref-b")
        for root in (self.work, self.ref_a, self.ref_b):
            os.makedirs(root)
        self._write(self.work, "existente.txt", "existente")
        self._write(self.ref_a, "existente.txt", "existente")
        self.profile = create_profile("Asignaciones", self.work)
        self.profile.sources = [
            Source(
                id="src_ref_a",
                name="Principal",
                root=self.ref_a,
                order=0,
                acts_as_destination=True,
                sync_destination=self.ref_a,
                sync_enabled=True,
            ),
            Source(
                id="src_ref_b",
                name="Herramientas",
                root=self.ref_b,
                order=1,
                acts_as_destination=True,
                sync_destination=self.ref_b,
                sync_enabled=True,
            ),
        ]
        for source in self.profile.sources:
            source.baseline = capture_source_baseline(self.work, source.root)
        save_profile(self.profile)
        self._write(self.work, "hola.txt", "nuevo")

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    @staticmethod
    def _write(root: str, relative: str, text: str) -> None:
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)

    def _window(self):
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        return window

    def _indeterminate_page(self, window):
        return window._profile_admin_pages["indeterminados"]

    @staticmethod
    def _item_for_path(page, path):
        for index in range(page.list.count()):
            item = page.list.item(index)
            entry = item.data(Qt.UserRole)
            if getattr(entry, "path", None) == path:
                return item
        return None

    def _analysis_for(self, source_id):
        return load_profile(self.profile.id)

    def test_new_file_detected_after_reanalysis(self):
        os.unlink(os.path.join(self.work, "hola.txt"))
        window = self._window()
        self.assertEqual(window.inicio_panel.pending_paths(), [])
        self.assertTrue(window.inicio_panel.assign_box.isHidden())
        # Paso 2-3 del escenario: crear el archivo y ejecutar el escáner.
        self._write(self.work, "hola.txt", "nuevo")
        window.reanalyze()
        self.assertEqual(window.inicio_panel.pending_paths(), ["hola.txt"])
        page = self._indeterminate_page(window)
        self.assertIsNotNone(self._item_for_path(page, "hola.txt"))

    def test_home_shows_dynamic_references_and_pending_new_file(self):
        window = self._window()
        panel = window.inicio_panel
        self.assertFalse(panel.assign_box.isHidden())
        self.assertEqual(panel.pending_paths(), ["hola.txt"])
        combo = panel._assign_combos["hola.txt"]
        labels = [
            combo.itemText(index) for index in range(1, combo.count())
        ]
        self.assertEqual(labels, ["Principal", "Herramientas"])
        ids = [
            combo.itemData(index) for index in range(1, combo.count())
        ]
        self.assertEqual(ids, ["src_ref_a", "src_ref_b"])
        # No se incorpora al inventario general de Inicio.
        rows_in_list = [
            panel.list.item(index).data(Qt.UserRole)
            for index in range(panel.list.count())
        ]
        self.assertNotIn("hola.txt", {row.path for row in rows_in_list})

    def test_home_pending_rows_have_no_redundant_notice_and_limited_combo_width(self):
        self._write(self.work, "segundo.txt", "nuevo2")
        window = self._window()
        window.reanalyze()
        panel = window.inicio_panel
        window.show()
        APP.processEvents()

        self.assertEqual(
            set(panel.pending_paths()), {"hola.txt", "segundo.txt"}
        )
        labels = [label.text() for label in panel.findChildren(QLabel)]
        self.assertNotIn(
            "Archivo nuevo pendiente de asignación", labels
        )
        self.assertEqual(
            panel.assign_title.text(),
            "Archivos nuevos pendientes de asignación",
        )

        from gipler.gui.theme import load_preference, semantic

        color = semantic(load_preference(), "new_in_dev")
        widths = []
        for path in panel.pending_paths():
            combo = panel._assign_combos[path]
            self.assertEqual(
                combo.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed
            )
            self.assertGreaterEqual(combo.maximumWidth(), 260)
            self.assertLessEqual(combo.maximumWidth(), 300)
            self.assertGreaterEqual(combo.width(), 260)
            self.assertLessEqual(combo.width(), 300)
            widths.append(combo.width())

            name = next(
                label
                for label in panel.findChildren(QLabel)
                if label.text() == path
            )
            self.assertIn(color.lower(), name.styleSheet().lower())
            assign_label = next(
                label
                for label in panel.findChildren(QLabel)
                if label.text() == "Asignar a"
            )
            self.assertGreater(combo.x(), assign_label.x())

        self.assertEqual(len(set(widths)), 1)

    def test_indeterminate_section_is_distinct_and_green(self):
        window = self._window()
        page = self._indeterminate_page(window)
        items = [page.list.item(i) for i in range(page.list.count())]
        header = next(
            item for item in items if item.text() == "Archivos nuevos"
        )
        self.assertEqual(header.flags(), Qt.NoItemFlags)
        item = self._item_for_path(page, "hola.txt")
        self.assertIsNotNone(item)
        self.assertIn("[Nuevo sin asignar]", item.text())
        from gipler.gui.theme import load_preference, semantic

        self.assertEqual(
            item.foreground().color().name(),
            semantic(load_preference(), "new_in_dev").lower(),
        )

    def test_context_menu_lists_active_references(self):
        window = self._window()
        page = self._indeterminate_page(window)
        item = self._item_for_path(page, "hola.txt")
        menu = page.context_menu_for(item)
        assign = next(
            action for action in menu.actions() if action.text() == "Asignar a"
        )
        self.assertIsNotNone(assign.menu())
        self.assertEqual(
            [action.text() for action in assign.menu().actions()],
            ["Principal", "Herramientas"],
        )

    def test_context_menu_assignment_persists_and_moves_file(self):
        window = self._window()
        page = self._indeterminate_page(window)
        item = self._item_for_path(page, "hola.txt")
        menu = page.context_menu_for(item)
        assign = next(
            action for action in menu.actions() if action.text() == "Asignar a"
        )
        assign.menu().actions()[1].trigger()  # Herramientas

        persisted = self._analysis_for("src_ref_b")
        self.assertEqual(persisted.assignments, {"hola.txt": "src_ref_b"})
        self.assertEqual(window.inicio_panel.pending_paths(), [])
        self.assertTrue(window.inicio_panel.assign_box.isHidden())
        page = self._indeterminate_page(window)
        self.assertIsNone(self._item_for_path(page, "hola.txt"))
        rows = {
            row.path: row
            for row in window.profile_analysis.rows_by_source["src_ref_b"]
        }
        self.assertEqual(rows["hola.txt"].axis_a, "new_in_dev")
        self.assertNotIn(
            "hola.txt",
            {row.path for row in window.profile_analysis.rows_by_source["src_ref_a"]},
        )
        # La asignación no copia nada.
        self.assertFalse(os.path.exists(os.path.join(self.ref_b, "hola.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.ref_a, "hola.txt")))

    def test_home_selector_performs_the_same_persistent_assignment(self):
        window = self._window()
        combo = window.inicio_panel._assign_combos["hola.txt"]
        index = combo.findData("src_ref_a")
        self.assertGreater(index, 0)
        combo.setCurrentIndex(index)

        persisted = load_profile(self.profile.id)
        self.assertEqual(persisted.assignments, {"hola.txt": "src_ref_a"})
        self.assertEqual(window.inicio_panel.pending_paths(), [])
        rows = {
            row.path: row
            for row in window.profile_analysis.rows_by_source["src_ref_a"]
        }
        self.assertEqual(rows["hola.txt"].axis_a, "new_in_dev")
        self.assertFalse(os.path.exists(os.path.join(self.ref_a, "hola.txt")))

    def test_assignment_survives_restart(self):
        window = self._window()
        window._assign_new_file("hola.txt", "src_ref_b")
        window.close()

        restarted = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.inicio_panel.pending_paths(), [])
        self.assertIn(
            "hola.txt",
            {row.path for row in restarted.profile_analysis.rows_by_source["src_ref_b"]},
        )


if __name__ == "__main__":
    unittest.main()
