"""Profile workspace GUI tests; no real copies or repository writes."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
)

from gipler.profile import (
    Source,
    add_exclusion,
    create_profile,
    list_profiles,
    load_profile,
    new_source_id,
    save_profile,
    set_last_profile_id,
)
from gipler.report import Row
from gipler.gui.profile_window import (
    EstablishBaselineDialog,
    ProfileWindow,
    SourceDialog,
)
from gipler.gui.main_window import GiplerWindow
from gipler.profile_analysis import analyze_profile
from gipler.recognition import MembershipState

APP = QApplication.instance() or QApplication([])


class ProfileWorkspaceGuiTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.reference = os.path.join(self.tmp.name, "reference")
        os.makedirs(os.path.join(self.work, "folder"))
        os.makedirs(self.reference)
        self._write(self.work, ".hidden", "hidden")
        self._write(self.work, "folder/file.txt", "work")
        self._write(self.work, "excluded.txt", "leave in place")
        self._write(self.reference, "folder/file.txt", "reference")
        self.profile = create_profile("Proyecto", self.work)
        self.profile.sources = [
            Source(
                id="src_reference",
                name="Referencia",
                root=self.reference,
                order=0,
            ),
            Source(
                id="src_disabled",
                name="Desactivada",
                kind="rules",
                enabled=False,
                order=1,
                config={"patterns": ["**"]},
            ),
        ]
        from gipler.profile import save_profile

        save_profile(self.profile)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    @staticmethod
    def _write(root: str, relative: str, text: str):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)

    def _window(self):
        window = ProfileWindow(load_profile(self.profile.id))
        self.addCleanup(window.close)
        return window

    @staticmethod
    def _index_for_path(page, path):
        def find(parent):
            for index in range(page.model.rowCount(parent)):
                child = page.model.index(index, 0, parent)
                node = page.model.node_at(child)
                if node.path == path:
                    return child
                nested = find(child)
                if nested is not None:
                    return nested
            return None

        return find(page.model.index(-1, 0))

    def test_tab_order_and_permanent_admin_tabs(self):
        window = self._window()
        self.assertEqual(
            [window.tabs.tabText(i) for i in range(window.tabs.count())],
            ["Inicio", "Referencia", "Desactivada (desactivada)", "Excluidos", "Indeterminados"],
        )
        self.assertIsNone(
            window.tabs.tabBar().tabButton(
                3, window.tabs.tabBar().ButtonPosition.LeftSide
            )
        )
        self.assertEqual(window.tabs.tabText(3), "Excluidos")
        self.assertEqual(window.tabs.tabText(4), "Indeterminados")

    def test_home_lists_all_physical_files_and_directories(self):
        window = self._window()
        home_page = window.tabs.widget(0)
        paths = {
            home_page.list.item(index).data(Qt.UserRole).path
            for index in range(home_page.list.count())
        }
        self.assertEqual(paths, {".hidden", "folder", "folder/file.txt", "excluded.txt"})

    def test_empty_excluded_tab_has_exact_message(self):
        window = self._window()
        excluded_page = window.tabs.widget(window.tabs.count() - 2)
        self.assertEqual(excluded_page.empty_label.text(), "Ningún archivo excluido")
        self.assertFalse(excluded_page.empty_label.isHidden())
        self.assertEqual(excluded_page.list.count(), 0)

    def test_excluded_tab_marks_inherited_children_and_restore_is_non_destructive(self):
        add_exclusion(self.profile.id, "folder/")
        window = self._window()
        excluded_page = window.tabs.widget(window.tabs.count() - 2)
        entries = [
            excluded_page.list.item(index).data(Qt.UserRole)
            for index in range(excluded_page.list.count())
        ]
        by_path = {entry.path: entry for entry in entries}
        self.assertIn("folder", by_path)
        self.assertIn("folder/file.txt", by_path)
        self.assertFalse(by_path["folder"].exclusion_inherited)
        self.assertTrue(by_path["folder/file.txt"].exclusion_inherited)
        self.assertIn("heredada", excluded_page.list.item(1).text())
        self.assertTrue(os.path.isfile(os.path.join(self.work, "folder", "file.txt")))

    def test_indeterminate_tab_and_resolve_using_rules(self):
        window = self._window()
        indeterminate_index = window.tabs.count() - 1
        indeterminate = window.tabs.widget(indeterminate_index)
        paths = {
            indeterminate.list.item(index).data(Qt.UserRole).path
            for index in range(indeterminate.list.count())
        }
        self.assertIn("excluded.txt", paths)
        unknown = next(
            entry for entry in window.analysis.indeterminate if entry.path == "excluded.txt"
        )
        self.assertEqual(unknown.membership.state, MembershipState.UNKNOWN)

    def test_disabled_source_retains_tab_and_is_not_an_active_recognizer(self):
        window = self._window()
        disabled = window._source_pages["src_disabled"]
        self.assertFalse(disabled.isEnabled())
        self.assertEqual(disabled.model.file_nodes(), [])
        self.assertEqual(
            load_profile(self.profile.id).source("src_disabled").config,
            {"patterns": ["**"]},
        )

    def test_source_edit_keeps_persistent_id_and_order(self):
        source = self.profile.sources[0]
        dialog = SourceDialog(source)
        dialog.name.setText("Referencia renombrada")
        dialog.root.setText(os.path.join(self.tmp.name, "otra-raiz"))
        updated = dialog.configured_source()
        self.assertEqual(updated.id, source.id)
        self.assertEqual(updated.order, source.order)
        self.assertEqual(updated.name, "Referencia renombrada")
        self.assertEqual(updated.root, os.path.abspath(os.path.join(self.tmp.name, "otra-raiz")))

    def test_browsing_reference_uses_directory_name_as_initial_label(self):
        dialog = SourceDialog(parent=None, sources=self.profile.sources)
        chosen = os.path.join(self.tmp.name, "My Reference")
        with patch(
            "gipler.gui.profile_window.QFileDialog.getExistingDirectory",
            return_value=chosen,
        ):
            dialog._browse()
        self.assertEqual(dialog.name.text(), "My Reference")
        self.assertEqual(dialog.root.text(), chosen)

    def test_new_sync_directory_defaults_to_reference_and_same_destination(self):
        dialog = SourceDialog(parent=None, sources=[])
        dialog.name.setText("Referencia nueva")
        dialog.root.setText(self.reference)
        configured = dialog.configured_source()

        self.assertEqual(dialog.windowTitle(), "Agregar directorio de sincronización")
        self.assertTrue(dialog.sync_enabled.isChecked())
        self.assertTrue(configured.acts_as_recognizer)
        self.assertTrue(configured.acts_as_destination)
        self.assertTrue(configured.sync_enabled)
        self.assertEqual(configured.root, self.reference)
        self.assertEqual(configured.sync_destination, self.reference)
        profile = type(self.profile)(
            id="profile_default_target",
            name="Destino por defecto",
            work_dir=self.work,
            sources=[configured],
        )
        analysis = analyze_profile(profile)
        entry = next(
            item for item in analysis.entries if item.path == "folder/file.txt"
        )
        self.assertEqual(entry.membership.source_ids, (configured.id,))
        self.assertEqual(entry.comparisons[configured.id], "modified_in_dev")
        self.assertEqual(entry.eligible_destination_source_id, configured.id)
        self.assertEqual(analysis.destination_roots[configured.id], self.reference)

    def test_baseline_confirmation_reviews_items_and_requires_explicit_checkbox(self):
        source = Source(
            id="src_baseline_review",
            name="Punto inicial",
            root=self.reference,
            acts_as_destination=True,
            sync_destination=self.reference,
            sync_enabled=True,
        )
        dialog = EstablishBaselineDialog(self.profile, source)
        self.addCleanup(dialog.close)

        self.assertIn(
            self.work,
            [label.text() for label in dialog.findChildren(QLabel)],
        )
        self.assertIn(
            "Sincronización: 1 archivo y 1 directorio",
            dialog.inventory_summary.text(),
        )
        self.assertIn("desconocidos", dialog.uncertain_summary.text())
        review_items = [
            dialog.review_list.item(index).text()
            for index in range(dialog.review_list.count())
        ]
        self.assertTrue(any("Desconocido: excluded.txt" in item for item in review_items))
        self.assertIsNone(source.baseline)
        self.assertFalse(dialog.establish_button.isEnabled())

        dialog.confirmation.setChecked(True)
        self.assertTrue(dialog.establish_button.isEnabled())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertTrue(dialog.baseline.established_at)
        self.assertEqual(
            {entry.path for entry in dialog.baseline.reference_entries},
            {"folder", "folder/file.txt"},
        )
        self.assertTrue(os.path.isfile(os.path.join(self.reference, "folder", "file.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.reference, "excluded.txt")))

    def test_read_only_reference_keeps_recognition_and_comparison(self):
        source = Source(
            id="src_readonly",
            name="Solo lectura",
            root=self.reference,
            acts_as_recognizer=True,
            acts_as_destination=False,
            sync_enabled=False,
        )
        dialog = SourceDialog(source, sources=[source])
        configured = dialog.configured_source()

        self.assertEqual(dialog.windowTitle(), "Editar directorio de sincronización")
        self.assertTrue(configured.acts_as_recognizer)
        self.assertFalse(configured.acts_as_destination)
        self.assertFalse(configured.sync_enabled)
        self.assertIn(
            "folder/file.txt",
            {
                row.path
                for row in analyze_profile(
                    type(self.profile)(
                        id=self.profile.id,
                        name=self.profile.name,
                        work_dir=self.work,
                        sources=[configured],
                    )
                ).rows_by_source[source.id]
            },
        )

    def test_alternative_destination_and_advanced_values_persist_with_source_id(self):
        alternate = os.path.join(self.tmp.name, "alternate")
        source = Source(
            id="src_advanced",
            name="Reglas avanzadas",
            kind="rules",
            root=self.reference,
            acts_as_recognizer=True,
            acts_as_destination=True,
            sync_enabled=True,
            sync_destination=self.reference,
            destination_source_id="src_target",
            config={
                "patterns": ["folder/**"],
                "exclusive": True,
                "provider_option": "keep",
            },
        )
        target = Source(
            id="src_target",
            name="Destino",
            root=self.reference,
            acts_as_destination=True,
            sync_enabled=True,
            sync_destination=self.reference,
        )
        dialog = SourceDialog(source, sources=[source, target])
        self.assertTrue(dialog.advanced.isHidden())
        dialog.advanced_toggle.setChecked(True)
        self.assertFalse(dialog.advanced.isHidden())
        dialog.alternative_destination.setChecked(True)
        dialog.sync_path.setText(alternate)
        dialog.name.setText("Reglas renombradas")
        configured = dialog.configured_source()
        self.assertEqual(configured.id, source.id)
        self.assertEqual(configured.name, "Reglas renombradas")
        self.assertEqual(configured.sync_destination, alternate)
        self.assertEqual(configured.destination_source_id, target.id)
        self.assertEqual(configured.config, source.config)

        self.profile.sources = [configured, target]
        save_profile(self.profile)
        reopened = load_profile(self.profile.id).source(source.id)
        self.assertEqual(reopened.id, source.id)
        self.assertEqual(reopened.name, "Reglas renombradas")
        self.assertEqual(reopened.sync_destination, alternate)
        self.assertEqual(reopened.destination_source_id, target.id)
        self.assertEqual(reopened.config["provider_option"], "keep")

    def test_existing_unlisted_recognition_kind_is_preserved_when_edited(self):
        source = Source(
            id="src_git_kind",
            name="Repositorio Git",
            kind="git_repository",
            root=self.reference,
            acts_as_recognizer=True,
            config={"provider_option": "unchanged"},
        )
        dialog = SourceDialog(source, sources=[source])
        configured = dialog.configured_source()
        self.assertEqual(configured.kind, "git_repository")
        self.assertEqual(configured.config, source.config)

    def test_empty_profile_always_has_admin_pages_and_order_after_reopen(self):
        empty_work = os.path.join(self.tmp.name, "empty-work")
        os.makedirs(empty_work)
        profile = create_profile("Vacío", empty_work)
        save_profile(profile)
        window = GiplerWindow(profile=load_profile(profile.id))
        self.addCleanup(window.close)

        self.assertEqual(
            set(window._profile_admin_pages),
            {"excluidos", "indeterminados"},
        )
        self.assertEqual(
            window._profile_admin_pages["excluidos"].empty_label.text(),
            "Ningún archivo excluido",
        )
        self.assertFalse(window._profile_admin_pages["excluidos"].empty_label.isHidden())
        self.assertEqual(
            window._profile_admin_pages["indeterminados"].empty_label.text(),
            "Ningún archivo indeterminado",
        )

        def nav_labels():
            return [
                action.defaultWidget().text()
                for action in window.nav_toolbar.actions()
                if action.defaultWidget() is not None
            ]

        self.assertEqual(
            nav_labels(), ["Inicio", "Excluidos", "Indeterminados"]
        )
        profile = load_profile(profile.id)
        profile.add_source(
            Source(id="src_generated", name="Primera", root=self.reference, order=0)
        )
        save_profile(profile)
        window.reanalyze()
        self.assertEqual(
            nav_labels(),
            ["Inicio", "Primera", "Excluidos", "Indeterminados"],
        )
        self.assertEqual(
            set(window._profile_admin_pages),
            {"excluidos", "indeterminados"},
        )
        profile = load_profile(profile.id)
        profile.add_source(
            Source(id="src_second", name="Segunda", root=self.reference, order=1)
        )
        save_profile(profile)
        window.reanalyze()
        self.assertEqual(
            nav_labels(),
            ["Inicio", "Primera", "Segunda", "Excluidos", "Indeterminados"],
        )
        reopened = GiplerWindow(profile=load_profile(profile.id))
        self.addCleanup(reopened.close)
        self.assertEqual(
            [
                action.defaultWidget().text()
                for action in reopened.nav_toolbar.actions()
                if action.defaultWidget() is not None
            ],
            ["Inicio", "Primera", "Segunda", "Excluidos", "Indeterminados"],
        )

    def test_profile_admin_pages_refresh_exclusions_without_touching_files(self):
        add_exclusion(self.profile.id, "folder/")
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        excluded_page = window._profile_admin_pages["excluidos"]
        entries = [
            excluded_page.list.item(index).data(Qt.UserRole)
            for index in range(excluded_page.list.count())
        ]
        by_path = {entry.path: entry for entry in entries}
        self.assertFalse(by_path["folder"].exclusion_inherited)
        self.assertTrue(by_path["folder/file.txt"].exclusion_inherited)
        self.assertTrue(os.path.isfile(os.path.join(self.work, "folder", "file.txt")))
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ):
            window._restore_profile_exclusion(by_path["folder"])
        self.assertTrue(os.path.isfile(os.path.join(self.work, "folder", "file.txt")))
        self.assertNotIn("folder/", load_profile(self.profile.id).exclusions)
        self.assertEqual(
            set(window._profile_admin_pages),
            {"excluidos", "indeterminados"},
        )
        self.assertEqual(window._profile_admin_pages["excluidos"].list.count(), 0)
        self.assertEqual(
            window._profile_admin_pages["excluidos"].empty_label.text(),
            "Ningún archivo excluido",
        )

    def test_profile_tree_defaults_to_differences_but_keeps_identical_rows(self):
        work = os.path.join(self.tmp.name, "tree-work")
        reference = os.path.join(self.tmp.name, "tree-reference")
        for root in (work, reference):
            os.makedirs(root)
        for path, text in (
            ("nested/deep/identical-a.txt", "same"),
            ("nested/deep/identical-b.txt", "same"),
            ("nested/deep/modified.txt", "dev edit"),
            ("nested/deep/new.txt", "new"),
            ("only-identical/same.txt", "same"),
        ):
            self._write(work, path, text)
        for path, text in (
            ("nested/deep/identical-a.txt", "same"),
            ("nested/deep/identical-b.txt", "same"),
            ("nested/deep/modified.txt", "reference"),
            ("nested/deep/missing-in-dev.txt", "reference only"),
            ("only-identical/same.txt", "same"),
        ):
            self._write(reference, path, text)
        profile = create_profile("Árbol", work)
        profile.sources = [
            Source(
                id="src_readonly_tree",
                name="Solo lectura",
                kind="rules",
                root=reference,
                acts_as_recognizer=True,
                acts_as_destination=False,
                sync_enabled=False,
                config={"patterns": ["nested/**", "only-identical/**"]},
            )
        ]
        save_profile(profile)
        window = GiplerWindow(profile=load_profile(profile.id))
        self.addCleanup(window.close)

        self.assertEqual(window.axis_a_box.currentText(), "Diferencias")
        all_model_rows = {
            node.path: node.row for node in window.tree_model.file_nodes()
        }
        self.assertEqual(all_model_rows["nested/deep/identical-a.txt"].axis_a, "identical")
        self.assertEqual(all_model_rows["nested/deep/modified.txt"].axis_a, "modified_in_dev")
        self.assertEqual(all_model_rows["nested/deep/new.txt"].axis_a, "new_in_dev")
        self.assertEqual(
            all_model_rows["nested/deep/missing-in-dev.txt"].axis_a,
            "missing_in_dev",
        )
        self.assertEqual(
            {node.path for node in window.tree_model.file_nodes()
             if getattr(node.row, "selection_key", None)},
            set(),
        )
        visible = self._visible_proxy_paths(window.proxy, window.tree_model)
        self.assertEqual(
            visible,
            {
                "nested",
                "nested/deep",
                "nested/deep/modified.txt",
                "nested/deep/new.txt",
                "nested/deep/missing-in-dev.txt",
            },
        )
        nested_index = self._find_proxy_path(
            window.proxy, window.tree_model, "nested"
        )
        deep_index = self._find_proxy_path(
            window.proxy, window.tree_model, "nested/deep"
        )
        self.assertTrue(window.dev_panel.tree.isExpanded(nested_index))
        self.assertTrue(window.dev_panel.tree.isExpanded(deep_index))
        window.dev_panel.tree.collapse(deep_index)
        self.assertFalse(window.dev_panel.tree.isExpanded(deep_index))
        window.dev_panel.tree.expand(deep_index)
        self.assertTrue(window.dev_panel.tree.isExpanded(deep_index))
        window.axis_a_box.setCurrentText("identical")
        identical_visible = self._visible_proxy_paths(window.proxy, window.tree_model)
        self.assertEqual(
            identical_visible,
            {
                "nested",
                "nested/deep",
                "nested/deep/identical-a.txt",
                "nested/deep/identical-b.txt",
                "only-identical",
                "only-identical/same.txt",
            },
        )
        from gipler.gui.models.comparison_tree import color_for_row
        from gipler.gui.theme import semantic

        self.assertEqual(
            color_for_row(all_model_rows["nested/deep/new.txt"], "oscuro"),
            semantic("oscuro", "new_in_dev"),
        )
        self.assertEqual(
            color_for_row(all_model_rows["nested/deep/modified.txt"], "oscuro"),
            semantic("oscuro", "modified_in_dev"),
        )
        self.assertEqual(
            color_for_row(all_model_rows["nested/deep/missing-in-dev.txt"], "oscuro"),
            semantic("oscuro", "missing_in_dev"),
        )

    def test_indeterminate_page_keeps_unknown_ambiguous_and_shared_distinct(self):
        work = os.path.join(self.tmp.name, "membership-work")
        reference = os.path.join(self.tmp.name, "membership-reference")
        os.makedirs(work)
        os.makedirs(reference)
        for path in ("unknown.txt", "ambiguous.txt", "shared.txt"):
            self._write(work, path, "work")
        for path in ("ambiguous.txt", "shared.txt"):
            self._write(reference, path, "reference")
        profile = create_profile("Pertenencias", work)
        profile.sources = [
            Source(id="src_directory", name="Directorio", root=reference),
            Source(
                id="src_ambiguous",
                name="Exclusiva",
                kind="rules",
                root=reference,
                config={"patterns": ["ambiguous.txt"], "exclusive": True},
            ),
            Source(
                id="src_shared",
                name="Compartida",
                kind="rules",
                root=reference,
                config={"patterns": ["shared.txt"]},
            ),
        ]
        save_profile(profile)
        window = GiplerWindow(profile=load_profile(profile.id))
        self.addCleanup(window.close)
        page = window._profile_admin_pages["indeterminados"]
        labels = {
            page.list.item(index).data(Qt.UserRole).path:
            page.list.item(index).text()
            for index in range(page.list.count())
        }
        self.assertIn("[Sin reconocimiento]", labels["unknown.txt"])
        self.assertIn("[Ambiguo o contradictorio]", labels["ambiguous.txt"])
        self.assertIn(
            "[Compartido (pertenencia múltiple válida)]", labels["shared.txt"]
        )
        shared = next(
            item for item in window.profile_analysis.entries
            if item.path == "shared.txt"
        )
        self.assertEqual(shared.membership.state, MembershipState.SHARED)

    @staticmethod
    def _visible_proxy_paths(proxy, model):
        paths = set()

        def visit(parent=QModelIndex()):
            for row in range(proxy.rowCount(parent)):
                index = proxy.index(row, 0, parent)
                node = model.node_at(proxy.mapToSource(index))
                paths.add(node.path)
                visit(index)

        visit()
        return paths

    @staticmethod
    def _find_proxy_path(proxy, model, target):
        def find(parent=QModelIndex()):
            for row in range(proxy.rowCount(parent)):
                index = proxy.index(row, 0, parent)
                node = model.node_at(proxy.mapToSource(index))
                if node.path == target:
                    return index
                nested = find(index)
                if nested is not None:
                    return nested
            return None

        return find()

    def test_main_opens_profile_directly_in_main_window(self):
        source = self.profile.sources[0]
        source.acts_as_destination = True
        source.sync_enabled = True
        source.sync_destination = self.reference
        save_profile(self.profile)

        from gipler.gui.profile_window import ProfileLauncherDialog
        from gipler.gui.main_window import main

        with patch.object(
            ProfileLauncherDialog,
            "exec",
            side_effect=AssertionError("el diálogo inicial no debe abrirse"),
        ), patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(main(), 0)
        window = APP._gipler_window
        self.addCleanup(window.close)
        self.assertIsInstance(window, GiplerWindow)
        self.assertNotIsInstance(window, ProfileWindow)
        self.assertEqual(window.profile.id, self.profile.id)
        self.assertEqual(window.repo_names(), ["src_reference", "src_disabled"])
        self.assertEqual(window._repo_root_for("src_reference"), self.reference)
        self.assertIn(
            "folder/file.txt",
            {node.path for node in window.tree_model.file_nodes()},
        )
        row = next(
            node.row
            for node in window.tree_model.file_nodes()
            if node.path == "folder/file.txt"
        )
        self.assertEqual(row.axis_a, "modified_in_dev")
        profile_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "Perfiles"
        )
        self.assertIn(
            "Administrar perfiles…",
            {action.text() for action in profile_menu.actions()},
        )

    def test_main_without_profiles_opens_empty_window_and_keeps_admin_menu(self):
        from gipler.gui.main_window import main

        with tempfile.TemporaryDirectory() as empty_home:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = empty_home
            try:
                with patch.object(QApplication, "exec", return_value=0):
                    self.assertEqual(main(), 0)
                window = APP._gipler_window
                self.addCleanup(window.close)
                self.assertIsNone(window.profile)
                self.assertEqual(window.rows, [])
                self.assertEqual(window.meta, {})
                self.assertFalse(window.inicio_panel.empty_state.isHidden())
                self.assertIn(
                    "No hay ningún perfil abierto",
                    window.inicio_panel.empty_state.text(),
                )
                profile_menu = next(
                    action.menu()
                    for action in window.menuBar().actions()
                    if action.text() == "Perfiles"
                )
                self.assertIn(
                    "Administrar perfiles…",
                    {action.text() for action in profile_menu.actions()},
                )
                self.assertEqual(list_profiles(), [])
                self.assertEqual(window.reanalyze(), "Sin perfil abierto")
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_main_prefers_last_used_profile(self):
        second_work = os.path.join(self.tmp.name, "second-work")
        os.makedirs(second_work)
        self._write(second_work, "backend.py", "dev")
        second = create_profile("Otro proyecto", second_work)
        set_last_profile_id(second.id)

        from gipler.gui.main_window import main

        with patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(main(), 0)
        window = APP._gipler_window
        self.addCleanup(window.close)
        self.assertEqual(window.profile.id, second.id)

    def test_main_reopens_after_close(self):
        from gipler.gui.main_window import main

        with patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(main(), 0)
        first = APP._gipler_window
        self.addCleanup(first.close)
        self.assertEqual(first.profile.id, self.profile.id)
        first.close()
        with patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(main(), 0)
        second = APP._gipler_window
        self.addCleanup(second.close)
        self.assertIsNot(second, first)
        self.assertEqual(second.profile.id, self.profile.id)

    def test_empty_window_opens_profile_from_admin_dialog(self):
        from gipler.gui.profile_window import ProfileLauncherDialog

        window = GiplerWindow()
        self.addCleanup(window.close)

        def choose_profile(dialog):
            dialog.profile_id = self.profile.id
            return QDialog.Accepted

        with patch.object(ProfileLauncherDialog, "exec", choose_profile):
            window._manage_profiles()
        replacement = APP._gipler_window
        self.addCleanup(replacement.close)
        self.assertIsNot(replacement, window)
        self.assertEqual(replacement.profile.id, self.profile.id)

    def test_legacy_command_opens_existing_fixed_flow(self):
        from gipler.gui import legacy

        row = Row("a.txt", "núcleo", "principal", "identical", "tracked_clean", [])
        info = {
            "meta": {"dev": "/tmp/dev", "principal": "/tmp/principal", "addons": "/tmp/addons"},
            "warnings": [],
            "snapshot": {"dev": {}, "repos": {}},
        }

        with patch(
            "gipler.config.configured_paths",
            return_value=("/tmp/dev", "/tmp/principal", "/tmp/addons"),
        ), patch(
            "gipler.analysis.analyze",
            return_value=("report", [row], info),
        ), patch.object(QApplication, "exec", return_value=7):
            self.assertEqual(legacy.main(), 7)
        window = APP._gipler_window
        self.addCleanup(window.close)
        self.assertIsNone(window.profile)
        self.assertEqual(window.rows, [row])
        self.assertEqual(window.meta["dev"], "/tmp/dev")
        self.assertEqual(window._destination, "principal")

    def test_profile_menu_switches_workspace_without_mixing_references(self):
        second_work = os.path.join(self.tmp.name, "second-work")
        second_reference = os.path.join(self.tmp.name, "second-reference")
        os.makedirs(second_work)
        os.makedirs(second_reference)
        self._write(second_work, "backend.py", "dev")
        self._write(second_reference, "backend.py", "reference")
        second = create_profile("Otro proyecto", second_work)
        second.sources = [
            Source(id="src_backend", name="Backend", root=second_reference, order=0)
        ]
        save_profile(second)
        first_window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(first_window.close)

        from gipler.gui.profile_window import ProfileLauncherDialog

        def choose_second(dialog):
            dialog.profile_id = second.id
            return QDialog.Accepted

        with patch.object(ProfileLauncherDialog, "exec", choose_second):
            first_window._manage_profiles()
        second_window = APP._gipler_window
        self.addCleanup(second_window.close)
        self.assertEqual(second_window.profile.id, second.id)
        self.assertEqual(second_window.repo_names(), ["src_backend"])
        self.assertEqual(second_window._repo_root_for("src_backend"), second_reference)
        self.assertEqual(second_window.meta["dev"], second_work)
        self.assertNotIn("src_reference", second_window.repo_names())

    def test_profile_reference_can_be_disabled_from_original_window(self):
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)

        def disable_reference(dialog):
            dialog.findChild(QListWidget).setCurrentRow(0)
            toggle = next(
                button
                for button in dialog.findChildren(QPushButton)
                if button.text() == "Desactivar"
            )
            toggle.click()
            dialog.accept()
            return QDialog.Accepted

        with patch.object(QDialog, "exec", disable_reference):
            window._manage_sources()
        self.assertFalse(window.profile.source("src_reference").enabled)
        self.assertFalse(window.repo_buttons["src_reference"].isEnabled())
        self.assertEqual(window._destination, "sin determinar")

    def test_original_profile_window_selection_prepares_without_copying(self):
        source = self.profile.sources[0]
        source.acts_as_destination = True
        source.sync_enabled = True
        source.sync_destination = self.reference
        save_profile(self.profile)
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        index = self._index_for_path_in_model(window.tree_model, "folder/file.txt")
        self.assertIsNotNone(index)
        window.tree_model.setData(index, Qt.Checked, Qt.CheckStateRole)
        operations = window.prepare_operations(show_dialog=False)
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].status, "copiable")
        self.assertTrue(os.path.isfile(os.path.join(self.reference, "folder", "file.txt")))
        self.assertEqual(
            {action.text() for action in window.menuBar().actions()},
            {"Herramientas", "Perfiles"},
        )

    @staticmethod
    def _index_for_path_in_model(model, path):
        def find(parent):
            for index in range(model.rowCount(parent)):
                child = model.index(index, 0, parent)
                node = model.node_at(child)
                if node.path == path:
                    return child
                nested = find(child)
                if nested is not None:
                    return nested
            return None

        return find(model.index(-1, 0))

    def test_copy_selection_syncs_between_home_and_source_and_prepares_only(self):
        destination = os.path.join(self.tmp.name, "destination")
        os.makedirs(destination)
        source = self.profile.sources[0]
        source.acts_as_destination = True
        source.sync_enabled = True
        source.sync_destination = destination
        save_profile(self.profile)
        window = self._window()
        home_page = window.tabs.widget(0)
        home_item = next(
            home_page.list.item(index)
            for index in range(home_page.list.count())
            if home_page.list.item(index).data(Qt.UserRole).path == "folder/file.txt"
        )
        self.assertTrue(home_item.flags() & Qt.ItemIsUserCheckable)
        home_item.setCheckState(Qt.Checked)
        key = ("src_reference", "folder/file.txt")
        self.assertIn(key, window.selection_ctrl)
        selected_before_inspection = set(window.selection_ctrl.keys)
        home_page.list.setCurrentItem(home_item)
        self.assertEqual(window.selection_ctrl.keys, selected_before_inspection)

        source_page = window._source_pages["src_reference"]
        source_index = self._index_for_path(source_page, "folder/file.txt")
        self.assertIsNotNone(source_index)
        self.assertEqual(source_page.model.data(source_index, Qt.CheckStateRole), Qt.Checked)
        operations = window.prepare_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].status, "copiable")
        self.assertEqual(window.btn_execute.text(), "Ejecutar copia (1)")
        self.assertFalse(os.path.exists(os.path.join(destination, "folder", "file.txt")))

        window.tabs.setCurrentIndex(0)
        window.tabs.setCurrentIndex(1)
        self.assertIn(key, window.selection_ctrl)
        self.assertEqual(window.ops_cache, operations)

    def test_ineligible_unknown_and_excluded_items_have_no_copy_checkbox(self):
        add_exclusion(self.profile.id, "excluded.txt")
        self.profile = load_profile(self.profile.id)
        source = self.profile.sources[0]
        source.acts_as_destination = True
        source.sync_enabled = True
        source.sync_destination = os.path.join(self.tmp.name, "destination")
        os.makedirs(source.sync_destination)
        save_profile(self.profile)
        window = self._window()
        home_page = window.tabs.widget(0)
        items = {
            home_page.list.item(index).data(Qt.UserRole).path:
            home_page.list.item(index)
            for index in range(home_page.list.count())
        }
        self.assertNotIn("excluded.txt", items)
        self.assertFalse(items[".hidden"].flags() & Qt.ItemIsUserCheckable)
        self.assertTrue(items["folder/file.txt"].flags() & Qt.ItemIsUserCheckable)

    def test_source_tab_displays_comparison_rows_and_double_click_uses_reference_root(self):
        self._write(self.reference, "only-reference.txt", "reference")
        window = self._window()
        page = window._source_pages["src_reference"]
        row = next(
            row for row in window.analysis.rows_by_source["src_reference"]
            if row.path == "only-reference.txt"
        )
        self.assertEqual(row.axis_a, "missing_in_dev")
        page.activated.emit(row, "src_reference")
        comparison = window._comparison_windows[-1]
        self.assertEqual(comparison.dev_root, self.work)
        self.assertEqual(comparison.repo_root, self.reference)

    def test_selecting_source_comparison_updates_original_inspector(self):
        window = self._window()
        entry = next(
            entry for entry in window.analysis.source_entries["src_reference"]
            if entry.path == "folder/file.txt"
        )
        window._inspect_entry(entry, "src_reference")
        self.assertIn(
            "Estado A (Dev↔repo): modified_in_dev",
            window.inspector.summary.toPlainText(),
        )
        self.assertIn("Pertenencia: recognized", window.inspector.summary.toPlainText())

    def test_excluding_comparison_path_refreshes_profile_without_touching_files(self):
        window = self._window()
        absolute = os.path.join(self.work, "folder", "file.txt")
        window._exclude_path("folder/file.txt")
        self.assertTrue(os.path.isfile(absolute))
        self.assertNotIn(
            "folder/file.txt",
            {entry.path for entry in window.analysis.entries},
        )
        self.assertIn(
            "folder/file.txt",
            {entry.path for entry in window.analysis.inventory.excluded},
        )

    def test_opening_a_missing_side_uses_the_physical_parent_directory(self):
        self._write(self.reference, "only-reference.txt", "reference")
        window = self._window()
        page = window._source_pages["src_reference"]
        row = next(
            row for row in window.analysis.rows_by_source["src_reference"]
            if row.path == "only-reference.txt"
        )
        self.assertEqual(row.axis_a, "missing_in_dev")
        with patch(
            "gipler.gui.profile_window.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            page.dev_panel._open_in_explorer("only-reference.txt", False)
        self.assertEqual(open_url.call_args.args[0].toLocalFile(), self.work)


if __name__ == "__main__":
    unittest.main()
