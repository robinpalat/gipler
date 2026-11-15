"""Vista Git de primer nivel: filtros, aislamiento y selectores."""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication, QLabel

from gipler.git_integration import GitOperationResult
from gipler.gui.main_window import GiplerWindow
from gipler.profile import (
    Source,
    capture_source_baseline,
    create_profile,
    load_profile,
    save_profile,
)
from .helpers import commit_all, git, make_repo, write

APP = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _visible_repo_items(window) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    proxy = window.repo_proxy
    source = proxy.sourceModel()

    def walk(parent: QModelIndex) -> None:
        for row in range(proxy.rowCount(parent)):
            index = proxy.index(row, 0, parent)
            node = source.node_at(proxy.mapToSource(index))
            if node is not None:
                if node.row is not None:
                    files.add(node.path)
                elif node.is_dir:
                    directories.add(node.path)
            walk(index)

    walk(QModelIndex())
    return files, directories


def _visible_repo_paths(window) -> set[str]:
    return _visible_repo_items(window)[0]


def _eligible_paths(window) -> set[str]:
    return set(window.git_tree_model.commit_eligible)


def _selected_commit_paths(window) -> set[str]:
    return set(window.git_tree_model.commit_selected)


def _select_commit_paths(window, paths) -> None:
    window.git_tree_model.add_commit_paths(set(paths))
    window._update_commit_ui()


def _start_commit(window, message: str) -> None:
    window._on_commit_requested()
    window.dest_panel.commit_message_edit.setText(message)
    window._on_commit_confirmed(message)


def _wait_commit_finished(window, timeout: float = 8.0) -> bool:
    bar = window.git_bars[window._destination]
    return _wait_until(
        lambda: not bar.controller.busy
        and not window.dest_panel.commit_message_row.isVisible(),
        timeout,
    )


def _index_for_path(window, path: str):
    proxy = window.repo_proxy
    source = proxy.sourceModel()

    def walk(parent: QModelIndex):
        for row in range(proxy.rowCount(parent)):
            index = proxy.index(row, 0, parent)
            node = source.node_at(proxy.mapToSource(index))
            if node is not None and node.path == path:
                return index
            found = walk(index)
            if found.isValid():
                return found
        return QModelIndex()

    return walk(QModelIndex())


class GitViewTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.git_repo = os.path.join(self.tmp.name, "git-repo")
        self.plain_dir = os.path.join(self.tmp.name, "plain")
        os.makedirs(self.work)
        os.makedirs(self.plain_dir)
        self._make_git_repo()
        self.profile = create_profile("Vista Git", self.work)
        self.profile.sources = [
            Source(
                id="src_git",
                name="Repo Git",
                root=self.git_repo,
                order=0,
                acts_as_destination=True,
                sync_destination=self.git_repo,
                sync_enabled=True,
            ),
            Source(
                id="src_plain",
                name="Plano",
                root=self.plain_dir,
                order=1,
                acts_as_destination=True,
                sync_destination=self.plain_dir,
                sync_enabled=True,
            ),
        ]
        for source in self.profile.sources:
            source.baseline = capture_source_baseline(self.work, source.root)
        save_profile(self.profile)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    def _make_git_repo(self) -> None:
        repo = make_repo(self.tmp.name, "git-repo")
        for name in ("clean.txt", "modified.txt", "staged.txt", "both.txt"):
            write(os.path.join(repo, name), "base\n")
        write(os.path.join(repo, "gui/play.sh"), "base\n")
        write(os.path.join(repo, "practice/term_practice.sh"), "base\n")
        write(os.path.join(repo, "addons/other.sh"), "base\n")
        write(os.path.join(repo, "locale/en.txt"), "base\n")
        write(os.path.join(repo, "README.md"), "base\n")
        write(os.path.join(repo, ".gitignore"), "ignored.txt\n")
        git(repo, "add", ".")
        commit_all(repo, "base")
        git(repo, "checkout", "-q", "-b", "side")
        write(os.path.join(repo, "conflict.txt"), "side\n")
        git(repo, "add", "conflict.txt")
        git(repo, "commit", "-q", "-m", "side")
        git(repo, "checkout", "-q", "master")
        write(os.path.join(repo, "conflict.txt"), "main\n")
        git(repo, "add", "conflict.txt")
        git(repo, "commit", "-q", "-m", "main")
        subprocess.run(
            ["git", "-C", repo, "merge", "side"],
            check=False,
            capture_output=True,
            text=True,
        )
        write(os.path.join(repo, "modified.txt"), "unstaged\n")
        write(os.path.join(repo, "gui/play.sh"), "unstaged\n")
        write(os.path.join(repo, "practice/term_practice.sh"), "unstaged\n")
        write(os.path.join(repo, "staged.txt"), "staged\n")
        git(repo, "add", "staged.txt")
        write(os.path.join(repo, "both.txt"), "staged\n")
        git(repo, "add", "both.txt")
        write(os.path.join(repo, "both.txt"), "unstaged again\n")
        write(os.path.join(repo, "untracked.txt"), "new\n")
        write(os.path.join(repo, "ignored.txt"), "ignored\n")
        self.git_repo = repo

    def _window(self):
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        window.show()
        window._on_repo("src_git")
        self.assertTrue(
            _wait_until(lambda: "src_git" in window.git_bars)
        )
        APP.processEvents()
        return window

    def _select_git_mode(self, window) -> None:
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("git"))
        APP.processEvents()
        _wait_until(lambda: window.git_bars["src_git"].available)

    def _set_git_filter(self, window, key: str) -> None:
        window.axis_b_box.setCurrentIndex(window.axis_b_box.findData(key))
        window.apply_filters()
        APP.processEvents()

    def test_contextual_toolbar_moves_git_actions_and_expands_commit(self):
        window = self._window()
        git_bar = window.git_bars["src_git"]

        self.assertTrue(window.sync_toolbar_controls.isVisible())
        self.assertFalse(window.git_bar_stack.isVisible())
        window.axis_b_box.setCurrentIndex(
            window.axis_b_box.findData("tracked_modified")
        )
        shared = window.context_label
        sync_text = shared.text()
        sync_font = shared.font()
        sync_alignment = int(shared.alignment())
        sync_object_name = shared.objectName()
        self.assertIn("visibles", sync_text)
        sync_right = shared.mapTo(window, shared.rect().topRight()).x()
        self.assertLessEqual(
            sync_right,
            window.search_button.mapTo(
                window, window.search_button.rect().topLeft()
            ).x(),
        )
        self._select_git_mode(window)
        self.assertTrue(_wait_until(lambda: git_bar.available))
        self.assertEqual(window.axis_b_box.currentData(), "unstaged_changes")

        self.assertFalse(window.sync_toolbar_controls.isVisible())
        self.assertTrue(window.git_bar_stack.isVisible())
        self.assertTrue(git_bar.fetch_button.isVisible())
        self.assertTrue(git_bar.pull_button.isVisible())
        self.assertTrue(git_bar.push_button.isVisible())
        self.assertTrue(git_bar.commit_button.isVisible())
        self.assertIs(window.context_label, shared)
        self.assertIs(window.visible_counter, shared)
        self.assertEqual(shared.objectName(), sync_object_name)
        self.assertEqual(int(shared.alignment()), sync_alignment)
        self.assertEqual(shared.font(), sync_font)
        self.assertEqual(shared.text(), git_bar.status.summary)
        self.assertTrue(shared.isVisible())
        self.assertLess(
            shared.mapTo(window, shared.rect().topRight()).x(),
            git_bar.fetch_button.mapTo(
                window, git_bar.fetch_button.rect().topLeft()
            ).x(),
        )
        self.assertLessEqual(
            shared.mapTo(
                window.filter_bar, shared.rect().topRight()
            ).x(),
            window.filter_bar.rect().right(),
        )
        self.assertFalse(window.search_button.isVisible())
        self.assertFalse(window.refresh_button.isVisible())
        self.assertFalse(window.incidences_box.isVisible())
        self.assertFalse(window.owner_box.isVisible())
        self.assertTrue(window.axis_b_box.isVisible())
        toolbar_labels = [
            label.text()
            for label in window.filter_bar.findChildren(QLabel)
        ]
        self.assertIn("Vista", toolbar_labels)
        self.assertIn("Filtro", toolbar_labels)
        self.assertIsNone(window.dest_panel._header_extra)
        self.assertEqual(
            window.findChildren(type(git_bar.fetch_button)).count(
                git_bar.fetch_button
            ),
            1,
        )
        self.assertEqual(window.dest_panel.commit_button.text(), "Confirmar selección")

        with patch.object(git_bar, "_can_commit", return_value=True):
            git_bar.begin_commit()
        self.assertTrue(git_bar.commit_row.isVisible())
        self.assertFalse(git_bar.commit_button.isVisible())
        self.assertEqual(
            git_bar.commit_row.mapTo(
                window, git_bar.commit_row.rect().center()
            ).y(),
            git_bar.fetch_button.mapTo(
                window, git_bar.fetch_button.rect().center()
            ).y(),
        )
        git_bar.cancel_commit()
        self.assertFalse(git_bar.commit_row.isVisible())
        self.assertTrue(git_bar.commit_button.isVisible())

        window.axis_b_box.setCurrentIndex(
            window.axis_b_box.findData("modified_unstaged")
        )
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("todos"))
        APP.processEvents()
        self.assertTrue(window.sync_toolbar_controls.isVisible())
        self.assertFalse(window.git_bar_stack.isVisible())
        self.assertEqual(window.axis_b_box.currentData(), "tracked_modified")

        self._select_git_mode(window)
        self.assertEqual(window.axis_b_box.currentData(), "modified_unstaged")
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("todos"))

    def test_git_view_filters_and_secondary_options(self):
        window = self._window()
        git_index = window.axis_a_box.findData("git")
        self.assertGreaterEqual(git_index, 0)
        self.assertTrue(window.axis_a_box.model().item(git_index).isEnabled())

        self._select_git_mode(window)
        self.assertEqual(window._view_mode, "git")
        self.assertIsNone(window.dev_panel.tree.model())
        self.assertTrue(window.repo_proxy.git_mode)
        self.assertIsNot(window.repo_proxy.sourceModel(), window.tree_model)
        self.assertEqual(window.axis_b_box.currentData(), "unstaged_changes")
        labels = [
            window.axis_b_box.itemText(index)
            for index in range(window.axis_b_box.count())
        ]
        self.assertEqual(
            labels,
            [
                "Todos los estados",
                "Cambios sin preparar",
                "Modificados sin preparar",
                "Preparados",
                "Sin seguimiento",
                "Ignorados",
                "Conflictos",
                "Tracked sin cambios",
            ],
        )
        self.assertTrue(window.axis_b_box.isVisible())
        self.assertLess(
            window.axis_a_box.geometry().right(),
            window.axis_b_box.geometry().left(),
        )

        expected = {
            "unstaged_changes": {
                "modified.txt",
                "both.txt",
                "gui/play.sh",
                "practice/term_practice.sh",
                "untracked.txt",
            },
            "modified_unstaged": {
                "modified.txt",
                "both.txt",
                "gui/play.sh",
                "practice/term_practice.sh",
            },
            "staged": {"staged.txt", "both.txt"},
            "untracked": {"untracked.txt"},
            "ignored": {"ignored.txt"},
            "conflicts": {"conflict.txt"},
            "tracked_clean": {
                "clean.txt",
                ".gitignore",
                "addons/other.sh",
                "locale/en.txt",
                "README.md",
            },
        }
        for key, paths in expected.items():
            self._set_git_filter(window, key)
            self.assertEqual(window.axis_b_box.currentData(), key)
            self.assertEqual(_visible_repo_paths(window), paths, key)

        self._set_git_filter(window, "todos")
        visible = _visible_repo_paths(window)
        self.assertIn("clean.txt", visible)
        self.assertIn("modified.txt", visible)
        self.assertIn("staged.txt", visible)
        self.assertIn("both.txt", visible)
        self.assertIn("untracked.txt", visible)
        self.assertIn("ignored.txt", visible)
        self.assertIn("conflict.txt", visible)

    def test_git_view_contextual_directories(self):
        window = self._window()
        self._select_git_mode(window)
        self._set_git_filter(window, "modified_unstaged")
        files, directories = _visible_repo_items(window)
        self.assertEqual(
            files,
            {
                "modified.txt",
                "both.txt",
                "gui/play.sh",
                "practice/term_practice.sh",
            },
        )
        self.assertEqual(directories, {"gui", "practice"})
        self.assertNotIn("addons", directories)
        self.assertNotIn("locale", directories)

    def test_git_view_empty_result_message(self):
        window = self._window()
        self._select_git_mode(window)
        self._set_git_filter(window, "untracked")
        self.assertFalse(window.dest_panel.empty_label.isVisible())
        window.repo_proxy.set_criteria(axis_b="nonexistent")
        window._update_counter()
        APP.processEvents()
        self.assertTrue(window.dest_panel.empty_label.isVisible())
        self.assertEqual(
            window.dest_panel.empty_label.text(),
            "No hay archivos que coincidan con este filtro",
        )
        self.assertFalse(window.dest_panel.tree.isVisible())

    def test_git_view_colors(self):
        from gipler.gui.theme import load_preference, semantic

        window = self._window()
        self._select_git_mode(window)
        self._set_git_filter(window, "todos")
        theme = load_preference()
        untracked_index = _index_for_path(window, "untracked.txt")
        modified_index = _index_for_path(window, "modified.txt")
        self.assertTrue(untracked_index.isValid())
        self.assertTrue(modified_index.isValid())
        untracked_color = window.repo_proxy.data(
            untracked_index, Qt.ForegroundRole
        )
        modified_color = window.repo_proxy.data(
            modified_index, Qt.ForegroundRole
        )
        self.assertEqual(
            untracked_color.name().lower(),
            semantic(theme, "new_in_dev").lower(),
        )
        self.assertEqual(
            modified_color.name().lower(),
            semantic(theme, "modified_in_dev").lower(),
        )

    def test_header_remains_fixed_when_git_filter_is_empty(self):
        window = self._window()
        self._select_git_mode(window)
        header_y = window.dest_panel.header.geometry().y()
        stack_y = window.git_bar_stack.geometry().y()
        window.repo_proxy.set_criteria(axis_b="nonexistent")
        window._update_counter()
        APP.processEvents()
        self.assertEqual(window.dest_panel.header.geometry().y(), header_y)
        self.assertEqual(window.git_bar_stack.geometry().y(), stack_y)
        self.assertTrue(window.dest_panel.empty_label.isVisible())
        self.assertFalse(window.dest_panel.tree.isVisible())

    def test_git_bar_hidden_in_normal_views(self):
        window = self._window()
        bar = window.git_bars["src_git"]
        self.assertFalse(window.git_bar_stack.isVisible())
        self.assertFalse(bar.isVisible())
        self.assertFalse(window.dest_panel.commit_bar.isVisible())
        self.assertFalse(window.dest_panel.commit_message_row.isVisible())
        for key in (
            "todos",
            "new_in_dev",
            "modified_in_dev",
            "identical",
            "missing_in_dev",
            "not_comparable",
            "diferencias",
        ):
            window.axis_a_box.setCurrentIndex(
                window.axis_a_box.findData(key)
            )
            window.apply_filters()
            APP.processEvents()
            self.assertFalse(
                window.git_bar_stack.isVisible(), key
            )
            self.assertFalse(bar.isVisible(), key)
            self.assertFalse(
                window.dest_panel.commit_bar.isVisible(), key
            )

    def test_git_bar_visible_in_git_view(self):
        window = self._window()
        self._select_git_mode(window)
        self.assertTrue(window.git_bar_stack.isVisible())
        self.assertTrue(window.git_bars["src_git"].isVisible())
        self.assertTrue(window.dest_panel.commit_bar.isVisible())

    def test_git_bar_transition_repeated(self):
        window = self._window()
        for _ in range(3):
            self._select_git_mode(window)
            self.assertTrue(window.git_bar_stack.isVisible())
            window.axis_a_box.setCurrentIndex(
                window.axis_a_box.findData("todos")
            )
            APP.processEvents()
            self.assertFalse(window.git_bar_stack.isVisible())
            self.assertFalse(window.dest_panel.commit_bar.isVisible())

    def test_commit_selection_and_filter_preserved_across_transition(self):
        window = self._window()
        self._select_git_mode(window)
        self._set_git_filter(window, "untracked")
        _select_commit_paths(window, {"untracked.txt"})
        window.axis_a_box.setCurrentIndex(
            window.axis_a_box.findData("todos")
        )
        APP.processEvents()
        self.assertFalse(window.git_bar_stack.isVisible())
        self._select_git_mode(window)
        self.assertEqual(window.axis_b_box.currentData(), "untracked")
        self.assertEqual(
            _selected_commit_paths(window), {"untracked.txt"}
        )

    def test_git_bar_hidden_for_non_git_reference(self):
        window = self._window()
        window._on_repo("src_plain")
        APP.processEvents()
        self.assertFalse(window.git_bar_stack.isVisible())
        self.assertFalse(window.dest_panel.commit_bar.isVisible())
        git_index = window.axis_a_box.findData("git")
        self.assertFalse(
            window.axis_a_box.model().item(git_index).isEnabled()
        )

    def test_normal_header_has_no_git_empty_space(self):
        window = self._window()
        self.assertFalse(window.git_bar_stack.isVisible())
        self.assertEqual(
            window.dest_panel.header.geometry().height(),
            window.dev_panel.header.geometry().height(),
        )

    def test_git_view_default_unstaged_changes_filter(self):
        window = self._window()
        self._select_git_mode(window)
        self.assertEqual(window.axis_b_box.currentData(), "unstaged_changes")
        files, directories = _visible_repo_items(window)
        self.assertEqual(
            files,
            {
                "modified.txt",
                "both.txt",
                "gui/play.sh",
                "practice/term_practice.sh",
                "untracked.txt",
            },
        )
        self.assertNotIn("staged.txt", files)
        self.assertNotIn("clean.txt", files)
        self.assertEqual(directories, {"gui", "practice"})

    def test_git_view_specific_filters_and_restoration(self):
        window = self._window()
        self._select_git_mode(window)
        self.assertEqual(window.axis_b_box.currentData(), "unstaged_changes")
        self._set_git_filter(window, "staged")
        self.assertEqual(
            _visible_repo_paths(window), {"staged.txt", "both.txt"}
        )
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("todos"))
        APP.processEvents()
        self.assertEqual(window.axis_b_box.currentData(), "todos")
        self.assertEqual(
            [
                window.axis_b_box.itemText(index)
                for index in range(window.axis_b_box.count())
            ],
            ["todos", "tracked_modified", "tracked_clean", "untracked", "ignored"],
        )
        self._select_git_mode(window)
        self.assertEqual(window.axis_b_box.currentData(), "staged")

    def test_git_view_uses_only_reference_repository(self):
        window = self._window()
        write(os.path.join(self.plain_dir, "solo-plano.txt"), "plano\n")
        self._select_git_mode(window)
        self.assertEqual(
            window.repo_proxy.repo_root,
            os.path.realpath(self.git_repo),
        )
        self.assertNotIn("solo-plano.txt", _visible_repo_paths(window))
        self.assertIn("modified.txt", _visible_repo_paths(window))

    def test_switch_between_git_and_normal_views(self):
        window = self._window()
        self._select_git_mode(window)
        self.assertEqual(window._view_mode, "git")
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("todos"))
        APP.processEvents()
        self.assertEqual(window._view_mode, "todos")
        self.assertIs(window.dev_panel.tree.model(), window.proxy)
        self.assertFalse(window.repo_proxy.git_mode)
        self.assertIs(window.repo_proxy.sourceModel(), window.tree_model)
        self.assertIsNone(window.git_tree_model)
        self.assertEqual(
            [
                window.axis_b_box.itemText(index)
                for index in range(window.axis_b_box.count())
            ],
            ["todos", "tracked_modified", "tracked_clean", "untracked", "ignored"],
        )

    def test_reference_without_git_disables_git_mode(self):
        window = self._window()
        self._select_git_mode(window)
        self.assertEqual(window._view_mode, "git")
        window._on_repo("src_plain")
        APP.processEvents()
        self.assertEqual(window._view_mode, "todos")
        git_index = window.axis_a_box.findData("git")
        self.assertFalse(window.axis_a_box.model().item(git_index).isEnabled())
        self.assertIs(window.dev_panel.tree.model(), window.proxy)
        self.assertFalse(window.repo_proxy.git_mode)

    def test_reference_change_resets_git_state(self):
        window = self._window()
        self._select_git_mode(window)
        window._on_repo("src_plain")
        APP.processEvents()
        window._on_repo("src_git")
        APP.processEvents()
        self.assertTrue(
            window.axis_a_box.model()
            .item(window.axis_a_box.findData("git"))
            .isEnabled()
        )
        self.assertEqual(window._view_mode, "todos")
        self.assertIs(window.repo_proxy.sourceModel(), window.tree_model)
        self._select_git_mode(window)
        self.assertEqual(window._view_mode, "git")
        self.assertIn("modified.txt", _visible_repo_paths(window))

    def test_main_window_has_no_plus_tab(self):
        window = self._window()
        labels = [
            action.defaultWidget().text()
            for action in window.nav_toolbar.actions()
            if action.defaultWidget() is not None
        ]
        self.assertNotIn("+", labels)
        self.assertEqual(
            labels,
            ["Inicio", "Repo Git", "Plano", "Excluidos", "Indeterminados"],
        )


if __name__ == "__main__":
    unittest.main()

class GitCommitViewTests(unittest.TestCase):
    """Flujo de commit visual en Vista Git, sin conflictos de merge."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.git_repo = os.path.join(self.tmp.name, "git-repo")
        self.plain_dir = os.path.join(self.tmp.name, "plain")
        os.makedirs(self.work)
        os.makedirs(self.plain_dir)
        self._make_git_repo()
        self.profile = create_profile("Commit Git", self.work)
        self.profile.sources = [
            Source(
                id="src_git",
                name="Repo Git",
                root=self.git_repo,
                order=0,
                acts_as_destination=True,
                sync_destination=self.git_repo,
                sync_enabled=True,
            ),
            Source(
                id="src_plain",
                name="Plano",
                root=self.plain_dir,
                order=1,
                acts_as_destination=True,
                sync_destination=self.plain_dir,
                sync_enabled=True,
            ),
        ]
        for source in self.profile.sources:
            source.baseline = capture_source_baseline(self.work, source.root)
        save_profile(self.profile)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    def _make_git_repo(self) -> None:
        repo = make_repo(self.tmp.name, "git-repo")
        for name in ("clean.txt", "modified.txt", "staged.txt", "both.txt"):
            write(os.path.join(repo, name), "base\n")
        write(os.path.join(repo, "gui/play.sh"), "base\n")
        write(os.path.join(repo, "practice/term_practice.sh"), "base\n")
        write(os.path.join(repo, "addons/other.sh"), "base\n")
        write(os.path.join(repo, "locale/en.txt"), "base\n")
        write(os.path.join(repo, "README.md"), "base\n")
        write(os.path.join(repo, ".gitignore"), "ignored.txt\n")
        git(repo, "add", ".")
        commit_all(repo, "base")
        write(os.path.join(repo, "modified.txt"), "unstaged\n")
        write(os.path.join(repo, "gui/play.sh"), "unstaged\n")
        write(os.path.join(repo, "practice/term_practice.sh"), "unstaged\n")
        write(os.path.join(repo, "staged.txt"), "staged\n")
        git(repo, "add", "staged.txt")
        write(os.path.join(repo, "both.txt"), "staged\n")
        git(repo, "add", "both.txt")
        write(os.path.join(repo, "both.txt"), "unstaged again\n")
        write(os.path.join(repo, "untracked.txt"), "new\n")
        write(os.path.join(repo, "ignored.txt"), "ignored\n")
        self.git_repo = repo

    def _window(self):
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        window.show()
        window._on_repo("src_git")
        self.assertTrue(
            _wait_until(lambda: "src_git" in window.git_bars)
        )
        APP.processEvents()
        return window

    def _select_git_mode(self, window) -> None:
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("git"))
        APP.processEvents()
        _wait_until(lambda: window.git_bars["src_git"].available)

    def _set_git_filter(self, window, key: str) -> None:
        window.axis_b_box.setCurrentIndex(window.axis_b_box.findData(key))
        window.apply_filters()
        APP.processEvents()

    def test_commit_selection_individual_and_select_all(self):
        window = self._window()
        self._select_git_mode(window)
        self.assertEqual(
            _eligible_paths(window),
            {
                "modified.txt",
                "both.txt",
                "gui/play.sh",
                "practice/term_practice.sh",
                "untracked.txt",
            },
        )
        self.assertEqual(_selected_commit_paths(window), set())
        self.assertFalse(window.dest_panel.commit_button.isEnabled())
        self.assertTrue(window.dest_panel.select_all_commit.isEnabled())
        self.assertEqual(
            window.dest_panel.select_all_commit.checkState(),
            Qt.CheckState.Unchecked,
        )

        _select_commit_paths(window, {"modified.txt"})
        self.assertEqual(_selected_commit_paths(window), {"modified.txt"})
        self.assertTrue(window.dest_panel.commit_button.isEnabled())
        self.assertEqual(
            window.dest_panel.commit_count_label.text(),
            "1 archivos seleccionados",
        )
        self.assertEqual(
            window.dest_panel.select_all_commit.checkState(),
            Qt.CheckState.PartiallyChecked,
        )

        _select_commit_paths(window, {"untracked.txt"})
        self.assertEqual(
            _selected_commit_paths(window),
            {"modified.txt", "untracked.txt"},
        )
        self.assertEqual(
            window.dest_panel.select_all_commit.checkState(),
            Qt.CheckState.PartiallyChecked,
        )

        window._on_select_all_commit_changed(2)
        self.assertEqual(
            _selected_commit_paths(window),
            {
                "modified.txt",
                "both.txt",
                "gui/play.sh",
                "practice/term_practice.sh",
                "untracked.txt",
            },
        )
        self.assertEqual(
            window.dest_panel.select_all_commit.checkState(),
            Qt.CheckState.Checked,
        )

        window._on_select_all_commit_changed(0)
        self.assertEqual(_selected_commit_paths(window), set())
        self.assertFalse(window.dest_panel.commit_button.isEnabled())
        self.assertEqual(
            window.dest_panel.select_all_commit.checkState(),
            Qt.CheckState.Unchecked,
        )

    def test_commit_selection_excludes_non_eligible_states(self):
        window = self._window()
        self._select_git_mode(window)
        eligible = _eligible_paths(window)
        for path in ("staged.txt", "clean.txt", "ignored.txt", "conflict.txt"):
            self.assertNotIn(path, eligible)

    def test_commit_selection_no_eligible_files(self):
        window = self._window()
        self._select_git_mode(window)
        window.git_tree_model.clear_commit_selection()
        self._set_git_filter(window, "ignored")
        window._update_commit_ui()
        self.assertEqual(window._visible_eligible_paths(), set())
        self.assertFalse(window.dest_panel.select_all_commit.isEnabled())
        self.assertFalse(window.dest_panel.commit_button.isEnabled())

    def test_commit_modified_file_only_leaves_other_staged_changes(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt"})
        window._on_commit_requested()
        self.assertTrue(window.dest_panel.commit_message_row.isVisible())
        self.assertIn(
            "preparados fuera de la selección",
            window.dest_panel.commit_warning.text(),
        )
        self.assertTrue(window.dest_panel.commit_include_staged.isVisible())
        _start_commit(window, "solo modified")
        self.assertTrue(_wait_commit_finished(window))
        self.assertTrue(window._git_files["modified.txt"].tracked_clean)
        self.assertTrue(window._git_files["staged.txt"].staged)
        self.assertEqual(_selected_commit_paths(window), set())
        self.assertFalse(window.dest_panel.commit_message_row.isVisible())

    def test_commit_include_staged_outside_selection(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt"})
        window._on_commit_requested()
        window.dest_panel.commit_include_staged.setChecked(True)
        _start_commit(window, "incluir preparados")
        self.assertTrue(_wait_commit_finished(window))
        self.assertTrue(window._git_files["modified.txt"].tracked_clean)
        self.assertTrue(window._git_files["staged.txt"].tracked_clean)

    def test_commit_untracked_and_modified_together(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt", "untracked.txt"})
        _start_commit(window, "mod y untracked")
        self.assertTrue(_wait_commit_finished(window))
        self.assertTrue(window._git_files["modified.txt"].tracked_clean)
        self.assertTrue(window._git_files["untracked.txt"].tracked_clean)

    def test_commit_with_staged_and_unstaged_changes(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"both.txt"})
        window._on_commit_requested()
        self.assertIn(
            "contenido completo",
            window.dest_panel.commit_warning.text(),
        )
        _start_commit(window, "contenido completo")
        self.assertTrue(_wait_commit_finished(window))
        self.assertTrue(window._git_files["both.txt"].tracked_clean)

    def test_commit_empty_message_is_rejected(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt"})
        window._on_commit_requested()
        window._on_commit_confirmed("")
        self.assertTrue(window.dest_panel.commit_error.isVisible())
        self.assertIn(
            "no puede estar vacío",
            window.dest_panel.commit_error.text(),
        )
        self.assertEqual(
            _selected_commit_paths(window), {"modified.txt"}
        )

    def test_commit_error_preserves_message(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt"})
        window._on_commit_requested()
        window.dest_panel.commit_message_edit.setText("mensaje conservado")
        window._on_git_commit_finished(
            GitOperationResult(
                kind="commit_selected",
                repository=self.git_repo,
                ok=False,
                message="Error simulado",
            )
        )
        self.assertEqual(
            window.dest_panel.commit_message_edit.text(),
            "mensaje conservado",
        )
        self.assertTrue(window.dest_panel.commit_error.isVisible())
        self.assertIn(
            "Error simulado",
            window.dest_panel.commit_error.text(),
        )

    def test_commit_selection_is_independent_of_sync_selection(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt"})
        self.assertEqual(window.selection_ctrl.keys, set())
        self.assertEqual(window.tree_model.checked_keys, set())

    def test_commit_does_not_push_automatically(self):
        window = self._window()
        self._select_git_mode(window)
        _select_commit_paths(window, {"modified.txt"})
        _start_commit(window, "sin push")
        self.assertTrue(_wait_commit_finished(window))
        bar = window.git_bars[window._destination]
        self.assertFalse(bar.controller.busy)
        self.assertNotEqual(bar.controller._purpose, "push")
