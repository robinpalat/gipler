"""Vista Git de primer nivel: filtros, aislamiento y selectores."""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

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
            _wait_until(lambda: window.git_bars["src_git"].available)
        )
        return window

    def _select_git_mode(self, window) -> None:
        window.axis_a_box.setCurrentIndex(window.axis_a_box.findData("git"))
        APP.processEvents()

    def _set_git_filter(self, window, key: str) -> None:
        window.axis_b_box.setCurrentIndex(window.axis_b_box.findData(key))
        window.apply_filters()
        APP.processEvents()

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
        self.assertEqual(window.axis_b_box.currentData(), "unstaged_changes")

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
