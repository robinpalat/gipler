"""Git integration tests: detection, read-only status, operations, and header UI.

Every repository is temporary.  No real user repository is touched.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from .helpers import commit_all, git, make_repo, write

from gipler.git_integration import (
    GitError,
    GitOperationResult,
    detect_repository,
    friendly_error,
    git_status,
    git_status_files,
    has_staged_changes,
    run_operation,
    validate_commit_message,
)
from gipler.gui.git_bar import GitBar
from gipler.gui.main_window import GiplerWindow
from gipler.gui.profile_window import ProfileComparisonPage, ProfileWindow
from gipler.profile import Source, create_profile, load_profile, save_profile

APP = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _branch(repo: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo, "symbolic-ref", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_bare(base: str, name: str = "origin.git") -> str:
    path = os.path.join(base, name)
    subprocess.run(
        ["git", "init", "--bare", "-q", path],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def _clone(origin: str, destination: str) -> str:
    subprocess.run(
        ["git", "clone", "-q", origin, destination],
        check=True,
        capture_output=True,
        text=True,
    )
    git(destination, "config", "user.email", "test@test.local")
    git(destination, "config", "user.name", "Test")
    return destination


def _seed_remote(tmp: str) -> tuple[str, str]:
    origin = _make_bare(tmp)
    seed = make_repo(tmp, "seed")
    write(os.path.join(seed, "file.txt"), "v1\n")
    commit_all(seed)
    git(seed, "remote", "add", "origin", origin)
    git(seed, "push", "-q", "-u", "origin", "HEAD")
    return origin, seed


class GitDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_detects_normal_repository_at_reference_root(self):
        repo = make_repo(self.tmp.name, "repo")
        detected = detect_repository(repo)
        self.assertIsNotNone(detected)
        self.assertEqual(os.path.realpath(detected.top_level), os.path.realpath(repo))

    def test_detects_repository_with_gitfile(self):
        git_dir = os.path.join(self.tmp.name, "separate.git")
        worktree = os.path.join(self.tmp.name, "worktree")
        subprocess.run(
            ["git", "init", "-q", "--separate-git-dir", git_dir, worktree],
            check=True,
            capture_output=True,
            text=True,
        )
        git(worktree, "config", "user.email", "test@test.local")
        git(worktree, "config", "user.name", "Test")
        write(os.path.join(worktree, "file.txt"), "content\n")
        commit_all(worktree)
        self.assertTrue(os.path.isfile(os.path.join(worktree, ".git")))
        detected = detect_repository(worktree)
        self.assertIsNotNone(detected)
        self.assertEqual(
            os.path.realpath(detected.top_level), os.path.realpath(worktree)
        )
        self.assertTrue(git_status(worktree).branch)

    def test_rejects_ordinary_git_file(self):
        directory = os.path.join(self.tmp.name, "not-a-repo")
        os.makedirs(directory)
        write(os.path.join(directory, ".git"), "this is just a file\n")
        self.assertIsNone(detect_repository(directory))
        with self.assertRaises(GitError):
            git_status(directory)

    def test_rejects_directory_without_git(self):
        directory = os.path.join(self.tmp.name, "plain")
        os.makedirs(directory)
        self.assertIsNone(detect_repository(directory))

    def test_does_not_claim_parent_repository_for_child_directory(self):
        repo = make_repo(self.tmp.name, "repo")
        child = os.path.join(repo, "child")
        os.makedirs(child)
        self.assertIsNone(detect_repository(child))


class GitErrorMessageTests(unittest.TestCase):
    def test_translates_common_failures_without_destructive_advice(self):
        self.assertIn(
            "autenticar",
            friendly_error("pull", "fatal: Authentication failed for ..."),
        )
        self.assertIn(
            "No se pudo conectar",
            friendly_error("fetch", "fatal: unable to access ... Could not resolve host"),
        )
        self.assertIn(
            "fast-forward",
            friendly_error("pull", "fatal: Not possible to fast-forward, aborting."),
        )
        self.assertIn(
            "cambios locales",
            friendly_error("pull", "error: Your local changes would be overwritten"),
        )
        self.assertIn(
            "Push rechazado",
            friendly_error("push", "! [rejected] main -> main (non-fast-forward)"),
        )


class GitStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_status_is_read_only_and_counts_changes(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "tracked.txt"), "v1\n")
        commit_all(repo)
        write(os.path.join(repo, "tracked.txt"), "v2\n")
        write(os.path.join(repo, "new.txt"), "new\n")
        before = {
            name: open(os.path.join(repo, name), "rb").read()
            for name in ("tracked.txt", "new.txt")
        }
        status = git_status(repo)
        after = {
            name: open(os.path.join(repo, name), "rb").read()
            for name in ("tracked.txt", "new.txt")
        }
        self.assertEqual(before, after)
        self.assertEqual(status.modified, 1)
        self.assertEqual(status.untracked, 1)
        self.assertEqual(status.staged, 0)
        self.assertIn("modificado", status.summary)
        self.assertIn("sin seguimiento", status.summary)

    def test_independent_references_have_independent_status(self):
        first = make_repo(self.tmp.name, "first")
        second = make_repo(self.tmp.name, "second")
        git(first, "checkout", "-q", "-b", "alpha")
        git(second, "checkout", "-q", "-b", "beta")
        write(os.path.join(second, "dirty.txt"), "dirty\n")
        one = git_status(first)
        two = git_status(second)
        self.assertEqual(one.branch, "alpha")
        self.assertEqual(two.branch, "beta")
        self.assertEqual(one.untracked, 0)
        self.assertEqual(two.untracked, 1)

    def test_git_status_files_classifies_all_states(self):
        repo = make_repo(self.tmp.name, "repo")
        for name in ("clean.txt", "modified.txt", "staged.txt", "both.txt"):
            write(os.path.join(repo, name), "base\n")
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
        write(os.path.join(repo, "staged.txt"), "staged\n")
        git(repo, "add", "staged.txt")
        write(os.path.join(repo, "both.txt"), "staged\n")
        git(repo, "add", "both.txt")
        write(os.path.join(repo, "both.txt"), "unstaged again\n")
        write(os.path.join(repo, "untracked.txt"), "new\n")
        write(os.path.join(repo, "ignored.txt"), "ignored\n")

        files = {item.path: item for item in git_status_files(repo)}
        self.assertEqual(files["clean.txt"].statuses, frozenset({"tracked_clean"}))
        self.assertEqual(
            files["modified.txt"].statuses, frozenset({"modified_unstaged"})
        )
        self.assertEqual(files["staged.txt"].statuses, frozenset({"staged"}))
        self.assertEqual(
            files["both.txt"].statuses,
            frozenset({"staged", "modified_unstaged"}),
        )
        self.assertEqual(files["untracked.txt"].statuses, frozenset({"untracked"}))
        self.assertEqual(files["ignored.txt"].statuses, frozenset({"ignored"}))
        self.assertEqual(files["conflict.txt"].statuses, frozenset({"conflicts"}))

    def test_remote_metadata_distinguishes_https_and_ssh(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        git(repo, "remote", "add", "origin", "https://example.invalid/owner/repo.git")
        https = git_status(repo)
        self.assertTrue(https.has_remote)
        self.assertEqual(https.remotes, ("origin",))
        self.assertTrue(https.uses_https_remote)
        self.assertFalse(https.uses_ssh_remote)
        git(
            repo,
            "remote",
            "set-url",
            "origin",
            "git@example.invalid:owner/repo.git",
        )
        ssh = git_status(repo)
        self.assertTrue(ssh.has_remote)
        self.assertFalse(ssh.uses_https_remote)
        self.assertTrue(ssh.uses_ssh_remote)

    def test_staged_detection_never_stages_anything(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        write(os.path.join(repo, "file.txt"), "v2\n")
        self.assertFalse(has_staged_changes(repo))
        self.assertEqual(git_status(repo).staged, 0)
        git(repo, "add", "file.txt")
        self.assertTrue(has_staged_changes(repo))


class GitOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_fetch_does_not_change_worktree_or_head(self):
        origin, _seed = _seed_remote(self.tmp.name)
        clone = _clone(origin, os.path.join(self.tmp.name, "clone"))
        other = _clone(origin, os.path.join(self.tmp.name, "other"))
        write(os.path.join(other, "remote.txt"), "remote\n")
        commit_all(other, "remote change")
        git(other, "push", "-q")
        head_before = subprocess.run(
            ["git", "-C", clone, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertFalse(os.path.exists(os.path.join(clone, "remote.txt")))
        result = run_operation(clone, "fetch")
        self.assertTrue(result.ok, result.message)
        head_after = subprocess.run(
            ["git", "-C", clone, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(head_before, head_after)
        self.assertFalse(os.path.exists(os.path.join(clone, "remote.txt")))
        self.assertGreaterEqual(git_status(clone).behind or 0, 1)

    def test_pull_fast_forward_updates_files(self):
        origin, _seed = _seed_remote(self.tmp.name)
        clone = _clone(origin, os.path.join(self.tmp.name, "clone"))
        other = _clone(origin, os.path.join(self.tmp.name, "other"))
        write(os.path.join(other, "file.txt"), "v2\n")
        commit_all(other, "update file")
        git(other, "push", "-q")
        result = run_operation(clone, "pull")
        self.assertTrue(result.ok, result.message)
        with open(os.path.join(clone, "file.txt"), encoding="utf-8") as file:
            self.assertEqual(file.read(), "v2\n")
        self.assertTrue(result.refresh_comparison)

    def test_pull_rejects_non_fast_forward_without_changing_worktree(self):
        origin, _seed = _seed_remote(self.tmp.name)
        clone = _clone(origin, os.path.join(self.tmp.name, "clone"))
        other = _clone(origin, os.path.join(self.tmp.name, "other"))
        write(os.path.join(clone, "local.txt"), "local\n")
        commit_all(clone, "local commit")
        write(os.path.join(other, "remote.txt"), "remote\n")
        commit_all(other, "remote commit")
        git(other, "push", "-q")
        head_before = subprocess.run(
            ["git", "-C", clone, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = run_operation(clone, "pull")
        self.assertFalse(result.ok)
        self.assertIn("fast-forward", result.message)
        head_after = subprocess.run(
            ["git", "-C", clone, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(head_before, head_after)
        self.assertFalse(os.path.exists(os.path.join(clone, "remote.txt")))

    def test_pull_rejects_local_changes_without_discarding_them(self):
        origin, _seed = _seed_remote(self.tmp.name)
        clone = _clone(origin, os.path.join(self.tmp.name, "clone"))
        other = _clone(origin, os.path.join(self.tmp.name, "other"))
        write(os.path.join(clone, "file.txt"), "local uncommitted\n")
        write(os.path.join(other, "file.txt"), "remote change\n")
        commit_all(other, "remote change")
        git(other, "push", "-q")
        result = run_operation(clone, "pull")
        self.assertFalse(result.ok)
        with open(os.path.join(clone, "file.txt"), encoding="utf-8") as file:
            self.assertEqual(file.read(), "local uncommitted\n")
        self.assertEqual(git_status(clone).modified, 1)

    def test_commit_without_staged_files_does_not_add_anything(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        write(os.path.join(repo, "file.txt"), "v2\n")
        head_before = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = run_operation(repo, "commit", message="should not happen")
        self.assertFalse(result.ok)
        self.assertIn("No hay archivos preparados", result.message)
        head_after = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(head_before, head_after)
        self.assertEqual(git_status(repo).staged, 0)
        self.assertEqual(git_status(repo).modified, 1)

    def test_commit_uses_only_staged_files(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "staged.txt"), "staged\n")
        write(os.path.join(repo, "unstaged.txt"), "unstaged\n")
        commit_all(repo)
        write(os.path.join(repo, "staged.txt"), "staged v2\n")
        write(os.path.join(repo, "unstaged.txt"), "unstaged v2\n")
        git(repo, "add", "staged.txt")
        result = run_operation(repo, "commit", message="only staged")
        self.assertTrue(result.ok, result.message)
        committed = subprocess.run(
            ["git", "-C", repo, "show", "--name-only", "--pretty=format:", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertIn("staged.txt", committed)
        self.assertNotIn("unstaged.txt", committed)
        self.assertEqual(git_status(repo).modified, 1)
        self.assertEqual(git_status(repo).staged, 0)

    def test_empty_commit_message_is_rejected(self):
        repo = make_repo(self.tmp.name, "repo")
        with self.assertRaises(GitError):
            validate_commit_message("   ")
        result = run_operation(repo, "commit", message="   ")
        self.assertFalse(result.ok)
        self.assertIn("mensaje", result.message.casefold())

    def test_push_success_and_rejected_push(self):
        origin, _seed = _seed_remote(self.tmp.name)
        clone = _clone(origin, os.path.join(self.tmp.name, "clone"))
        write(os.path.join(clone, "local.txt"), "local\n")
        commit_all(clone, "local")
        success = run_operation(clone, "push")
        self.assertTrue(success.ok, success.message)

        other = _clone(origin, os.path.join(self.tmp.name, "other"))
        write(os.path.join(other, "remote.txt"), "remote\n")
        commit_all(other, "remote")
        git(other, "push", "-q")
        write(os.path.join(clone, "more.txt"), "more\n")
        commit_all(clone, "more")
        rejected = run_operation(clone, "push")
        self.assertFalse(rejected.ok)
        self.assertIn("Push rechazado", rejected.message)


class GitBarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    def test_buttons_have_icon_only_order_and_tooltips(self):
        repo = make_repo(self.tmp.name, "repo")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        self.assertEqual(
            [button.toolTip().split(":")[0] for button in bar.action_buttons],
            ["Fetch", "Pull --ff-only", "Commit", "Push"],
        )
        self.assertTrue(all(not button.icon().isNull() for button in bar.action_buttons))
        self.assertTrue(all(button.iconSize().width() == 18 for button in bar.action_buttons))
        self.assertTrue(all(button.iconSize().height() == 18 for button in bar.action_buttons))
        self.assertTrue(all(button.width() == 28 for button in bar.action_buttons))
        self.assertTrue(all(button.height() == 28 for button in bar.action_buttons))
        self.assertTrue(all(not button.text() for button in bar.action_buttons))

    def test_no_bar_for_non_git_reference(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        bar = GitBar(plain)
        self.addCleanup(bar.close)
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.status_checked))
        self.assertFalse(bar.available)
        self.assertTrue(bar.isHidden())

    def test_status_label_updates_after_external_change(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertIn("limpio", bar.status_label.text())
        write(os.path.join(repo, "file.txt"), "v2\n")
        bar.refresh_status()
        self.assertTrue(
            _wait_until(lambda: bar.status is not None and bar.status.modified == 1)
        )
        self.assertIn("modificado", bar.status_label.text())

    def test_commit_inline_validation_and_message_preservation(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        write(os.path.join(repo, "file.txt"), "v2\n")
        git(repo, "add", "file.txt")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        bar.begin_commit()
        self.assertTrue(bar.commit_expanded)
        bar.commit_edit.setText("   ")
        bar._confirm_commit()
        self.assertTrue(bar.commit_expanded)
        self.assertTrue(bar.commit_error.isVisible())
        bar.commit_edit.setText("mensaje que debe conservarse")
        bar._on_operation_finished(
            GitOperationResult(
                kind="commit",
                repository=repo,
                ok=False,
                message="Error simulado",
            )
        )
        self.assertTrue(bar.commit_expanded)
        self.assertEqual(bar.commit_edit.text(), "mensaje que debe conservarse")
        self.assertIn("Error simulado", bar.commit_error.text())
        bar.cancel_commit()
        self.assertFalse(bar.commit_expanded)

    def test_commit_without_staged_files_is_disabled_and_explained(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        write(os.path.join(repo, "file.txt"), "v2\n")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertFalse(bar.commit_button.isEnabled())
        self.assertIn("No hay archivos preparados", bar.commit_button.toolTip())
        bar.begin_commit()
        self.assertFalse(bar.commit_expanded)
        self.assertTrue(bar.commit_error.isVisible())
        self.assertIn("No hay archivos preparados", bar.commit_error.text())

    def test_commit_with_staged_file_compacts_after_success(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        write(os.path.join(repo, "file.txt"), "v2\n")
        git(repo, "add", "file.txt")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        bar.begin_commit()
        bar.commit_edit.setText("cambio preparado")
        bar._confirm_commit()
        self.assertTrue(_wait_until(lambda: not bar.commit_expanded))
        log = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(log, "cambio preparado")
        self.assertTrue(_wait_until(lambda: bar.status is not None and bar.status.clean))

    def test_bar_hides_when_repository_disappears(self):
        repo = make_repo(self.tmp.name, "repo")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        shutil.rmtree(os.path.join(repo, ".git"))
        bar.refresh_status()
        self.assertTrue(_wait_until(lambda: not bar.available))
        self.assertTrue(bar.isHidden())

    def test_pull_confirmation_can_cancel(self):
        _origin, repo = _seed_remote(self.tmp.name)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            bar.pull()
        self.assertFalse(bar.controller.busy)

    def test_push_confirmation_can_cancel(self):
        _origin, repo = _seed_remote(self.tmp.name)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            bar.push()
        self.assertFalse(bar.controller.busy)

    def test_operation_buttons_without_remote_and_upstream(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertFalse(bar.fetch_button.isEnabled())
        self.assertFalse(bar.pull_button.isEnabled())
        self.assertFalse(bar.push_button.isEnabled())
        self.assertFalse(bar.commit_button.isEnabled())
        self.assertIn("No hay remoto", bar.fetch_button.toolTip())
        self.assertIn("upstream", bar.pull_button.toolTip())
        self.assertIn("archivos preparados", bar.commit_button.toolTip())

    def test_fetch_enabled_with_remote_but_no_upstream(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "v1\n")
        commit_all(repo)
        origin = _make_bare(self.tmp.name)
        git(repo, "remote", "add", "origin", origin)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertTrue(bar.fetch_button.isEnabled())
        self.assertFalse(bar.pull_button.isEnabled())
        self.assertFalse(bar.push_button.isEnabled())
        self.assertFalse(bar.commit_button.isEnabled())
        self.assertIn("upstream", bar.pull_button.toolTip())

    def test_conflicts_block_pull_commit_push_but_not_fetch(self):
        repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(repo, "file.txt"), "base\n")
        commit_all(repo)
        default_branch = _branch(repo)
        git(repo, "checkout", "-q", "-b", "other")
        write(os.path.join(repo, "file.txt"), "other\n")
        commit_all(repo, "other")
        git(repo, "checkout", "-q", default_branch)
        write(os.path.join(repo, "file.txt"), "main\n")
        commit_all(repo, "main")
        subprocess.run(
            ["git", "-C", repo, "merge", "other"],
            check=False,
            capture_output=True,
            text=True,
        )
        origin = _make_bare(self.tmp.name)
        git(repo, "remote", "add", "origin", origin)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertGreater(bar.status.unmerged, 0)
        self.assertTrue(bar.fetch_button.isEnabled())
        self.assertFalse(bar.pull_button.isEnabled())
        self.assertFalse(bar.commit_button.isEnabled())
        self.assertFalse(bar.push_button.isEnabled())
        self.assertIn("conflictos", bar.commit_button.toolTip())

    def test_staged_file_enables_commit(self):
        _origin, repo = _seed_remote(self.tmp.name)
        write(os.path.join(repo, "file.txt"), "staged\n")
        git(repo, "add", "file.txt")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertTrue(bar.commit_button.isEnabled())
        bar.begin_commit()
        self.assertTrue(bar.commit_expanded)
        bar.cancel_commit()

    def test_status_queries_are_serialized(self):
        repo = make_repo(self.tmp.name, "repo")
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        with patch.object(
            bar.controller, "_start", wraps=bar.controller._start
        ) as start:
            bar.refresh_status()
            bar.refresh_status()
            self.assertEqual(start.call_count, 1)
        bar.controller.shutdown()

    def test_polling_stops_during_operation(self):
        _origin, repo = _seed_remote(self.tmp.name)
        bar = GitBar(repo)
        self.addCleanup(bar.close)
        bar.show()
        bar.activate()
        self.assertTrue(_wait_until(lambda: bar.available))
        self.assertTrue(bar._refresh_timer.isActive())
        fake_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(fake_dir, exist_ok=True)
        fake_git = os.path.join(fake_dir, "git")
        with open(fake_git, "w", encoding="utf-8") as file:
            file.write("#!/bin/sh\nsleep 1\nexit 0\n")
        os.chmod(fake_git, 0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = fake_dir + os.pathsep + old_path
        try:
            bar.fetch()
            self.assertTrue(bar.controller.operation_in_progress)
            self.assertFalse(bar._refresh_timer.isActive())
        finally:
            os.environ["PATH"] = old_path
            bar.controller.shutdown()

    def test_qprocess_can_receive_gipler_askpass_without_overwriting_user_env(self):
        repo = make_repo(self.tmp.name, "repo")
        fake_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(fake_dir, exist_ok=True)
        fake_git = os.path.join(fake_dir, "git")
        with open(fake_git, "w", encoding="utf-8") as file:
            file.write("#!/bin/sh\nsleep 1\nexit 0\n")
        os.chmod(fake_git, 0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = fake_dir + os.pathsep + old_path
        try:
            bar = GitBar(repo)
            self.addCleanup(bar.close)
            with patch(
                "gipler.gui.git_bar.configure_askpass",
                return_value={
                    "SSH_ASKPASS": "/tmp/gipler-askpass",
                    "SSH_ASKPASS_REQUIRE": "force",
                },
            ):
                bar.controller._start(
                    "operation", ["fetch"], kind="fetch", no_prompt=True
                )
            env = bar.controller.processEnvironment()
            self.assertEqual(env.value("SSH_ASKPASS"), "/tmp/gipler-askpass")
            self.assertEqual(env.value("SSH_ASKPASS_REQUIRE"), "force")
            self.assertEqual(env.value("GIT_TERMINAL_PROMPT"), "0")
        finally:
            os.environ["PATH"] = old_path

    def test_qprocess_inherits_ssh_environment_and_disables_terminal_prompt(self):
        repo = make_repo(self.tmp.name, "repo")
        fake_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(fake_dir, exist_ok=True)
        fake_git = os.path.join(fake_dir, "git")
        with open(fake_git, "w", encoding="utf-8") as file:
            file.write("#!/bin/sh\nsleep 1\nexit 0\n")
        os.chmod(fake_git, 0o755)
        old_path = os.environ.get("PATH", "")
        old_sock = os.environ.get("SSH_AUTH_SOCK")
        os.environ["PATH"] = fake_dir + os.pathsep + old_path
        os.environ["SSH_AUTH_SOCK"] = "/tmp/gipler-test-agent.sock"
        try:
            bar = GitBar(repo)
            self.addCleanup(bar.close)
            bar.controller._start(
                "operation", ["fetch"], kind="fetch", no_prompt=True
            )
            env = bar.controller.processEnvironment()
            self.assertEqual(
                env.value("SSH_AUTH_SOCK"), "/tmp/gipler-test-agent.sock"
            )
            self.assertEqual(env.value("GIT_TERMINAL_PROMPT"), "0")
            self.assertEqual(env.value("LC_ALL"), "C")
            self.assertEqual(env.value("HOME"), os.environ.get("HOME"))
            self.assertEqual(
                [line for line in bar.findChildren(QLineEdit)],
                [bar.commit_edit],
            )
        finally:
            os.environ["PATH"] = old_path
            if old_sock is None:
                os.environ.pop("SSH_AUTH_SOCK", None)
            else:
                os.environ["SSH_AUTH_SOCK"] = old_sock

    def test_git_process_does_not_block_calling_thread(self):
        fake_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(fake_dir)
        fake_git = os.path.join(fake_dir, "git")
        with open(fake_git, "w", encoding="utf-8") as file:
            file.write("#!/bin/sh\nsleep 1\nexit 0\n")
        os.chmod(fake_git, 0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = fake_dir + os.pathsep + old_path
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old_path))
        bar = GitBar(os.path.join(self.tmp.name, "repo"))
        self.addCleanup(bar.close)
        started = time.monotonic()
        bar.activate()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.5)
        self.assertTrue(bar.controller.busy)
        bar.controller.shutdown()


class GitWindowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._restore_home)
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.work)
        self.repo = make_repo(self.tmp.name, "repo")
        write(os.path.join(self.repo, "file.txt"), "repo\n")
        commit_all(self.repo)
        self.profile = create_profile("Git", self.work)
        self.profile.sources = [
            Source(id="src_repo", name="Repo", root=self.repo, order=0)
        ]
        save_profile(self.profile)

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    def test_main_window_shows_bar_only_on_reference_page(self):
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        window.show()
        APP.processEvents()
        self.assertFalse(window.git_bar_stack.isVisible())
        window._on_repo("src_repo")
        bar = window.git_bars["src_repo"]
        self.assertTrue(_wait_until(lambda: window.git_bar_stack.isVisible()))
        self.assertTrue(bar.available)
        self.assertEqual(bar.repository, os.path.realpath(self.repo))
        self.assertIs(window.git_bar_stack.parent(), window.dest_panel)
        self.assertGreaterEqual(
            window.dest_panel.header.indexOf(window.git_bar_stack), 0
        )
        self.assertIs(bar.parent(), window.git_bar_stack)
        self.assertEqual(window.dest_panel.title_label.full_text(), "repo")
        self.assertTrue(window.dest_panel.folder_icon.isVisible())
        window._show_inicio()
        APP.processEvents()
        self.assertFalse(window.git_bar_stack.isVisible())
        self.assertFalse(bar._active)

    def test_commit_expands_in_reference_header_without_tree_rebuild(self):
        write(os.path.join(self.repo, "file.txt"), "staged\n")
        git(self.repo, "add", "file.txt")
        window = GiplerWindow(profile=load_profile(self.profile.id))
        self.addCleanup(window.close)
        window.show()
        window._on_repo("src_repo")
        bar = window.git_bars["src_repo"]
        self.assertTrue(_wait_until(lambda: bar.available))
        model = window.tree_model
        row_count = model.rowCount()
        self.assertTrue(bar.commit_button.isEnabled())
        bar.begin_commit()
        self.assertTrue(bar.commit_expanded)
        self.assertIs(window.tree_model, model)
        self.assertEqual(window.tree_model.rowCount(), row_count)
        bar.cancel_commit()
        self.assertFalse(bar.commit_expanded)

    def test_profile_tabs_have_independent_bars(self):
        second = make_repo(self.tmp.name, "second")
        write(os.path.join(second, "other.txt"), "other\n")
        commit_all(second)
        self.profile.sources.append(
            Source(id="src_second", name="Second", root=second, order=1)
        )
        save_profile(self.profile)
        window = ProfileWindow(load_profile(self.profile.id))
        self.addCleanup(window.close)
        window.show()
        APP.processEvents()
        first_page = window.tabs.widget(1)
        second_page = window.tabs.widget(2)
        self.assertIsInstance(first_page, ProfileComparisonPage)
        self.assertIsInstance(second_page, ProfileComparisonPage)
        window.tabs.setCurrentIndex(1)
        self.assertTrue(_wait_until(lambda: first_page.git_bar.available))
        self.assertTrue(first_page.git_bar._active)
        self.assertIs(first_page.git_bar.parent(), first_page.reference_panel)
        self.assertGreaterEqual(
            first_page.reference_panel.header.indexOf(first_page.git_bar), 0
        )
        self.assertEqual(first_page.layout().indexOf(first_page.git_bar), -1)
        self.assertTrue(first_page.reference_panel.folder_icon.isVisible())
        self.assertEqual(
            first_page.reference_panel.title_label.full_text(),
            os.path.basename(os.path.normpath(self.repo)),
        )
        window.tabs.setCurrentIndex(2)
        self.assertTrue(_wait_until(lambda: second_page.git_bar.available))
        self.assertFalse(first_page.git_bar._active)
        self.assertTrue(second_page.git_bar._active)
        self.assertNotEqual(
            first_page.git_bar.repository, second_page.git_bar.repository
        )
        window.tabs.setCurrentIndex(window.tabs.count() - 2)
        APP.processEvents()
        self.assertFalse(first_page.git_bar._active)
        self.assertFalse(second_page.git_bar._active)


if __name__ == "__main__":
    unittest.main()
