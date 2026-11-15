"""Tests del motor de copia (solo directorios temporales)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from gipler.copy_engine import (
    _sha,
    _sha_fd,
    build_operations,
    execute_operations,
    preview,
)
from gipler.profile import Source, create_profile, save_profile
from gipler.profile_analysis import analyze_profile
from gipler.report import Row
from .helpers import git, make_repo, write, commit_all


def _setup(extra_dev=None, extra_repo=None, local=None, ignore=None, links=None):
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    root = tmp.name
    dev = os.path.join(root, "dev")
    repo = make_repo(root, "repo")
    os.makedirs(os.path.join(dev, "Ext"))
    for rel in ("Ext/cnfg.sh", "Ext/same.txt", "Ext/mod.txt"):
        write(os.path.join(dev, *rel.split("/")), "x\n")
        write(os.path.join(repo, *rel.split("/")), "x\n")
    if ignore:
        write(os.path.join(repo, ".gitignore"), ignore)
    commit_all(repo)
    if local:
        for rel, content in local.items():
            write(os.path.join(repo, *rel.split("/")), content)
    if links:
        for rel, target in links.items():
            path = os.path.join(dev, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            os.symlink(target, path)
    if extra_dev:
        for rel, content in extra_dev.items():
            write(os.path.join(dev, *rel.split("/")), content, executable=rel.endswith(".sh"))
    if extra_repo:
        for rel, content in extra_repo.items():
            write(os.path.join(repo, *rel.split("/")), content)

    import uuid

    profile = create_profile(f"CopyEngine {uuid.uuid4().hex[:8]}", dev)
    profile.sources = [
        Source(
            id="src_000000",
            name="Repo",
            root=repo,
            order=0,
            acts_as_recognizer=True,
            acts_as_destination=True,
            sync_enabled=True,
            sync_destination=repo,
        )
    ]
    dev_files = set()
    for base, _dirs, files in os.walk(dev):
        for name in files:
            dev_files.add(os.path.relpath(os.path.join(base, name), dev).replace(os.sep, "/"))
    for rel in sorted(dev_files):
        profile.assign_path(rel, "src_000000")
    save_profile(profile)
    analysis = analyze_profile(profile)
    rows = [
        row
        for source_rows in analysis.rows_by_source.values()
        for row in source_rows
    ]
    repos = {"src_000000": repo}

    def sel(paths):
        return {(r.destination, r.path) for r in rows if r.path in paths}

    return tmp, dev, repo, rows, analysis, repos, sel


def _ops(tmp, dev, repo, rows, analysis, repos, paths):
    selection = {(r.destination, r.path) for r in rows if r.path in paths}
    return build_operations(rows, selection, dev, repos, analysis.snapshot)


class CopyEngineTests(unittest.TestCase):
    def test_new_and_modified_copy(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/new.txt": "n\n", "Ext/mod.txt": "new\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/new.txt", "Ext/mod.txt"})
        self.assertTrue(all(o.status == "copiable" for o in ops), ops)
        res = execute_operations(ops, authorized=True)
        self.assertTrue(all(r["status"] == "copiada" for r in res), res)
        self.assertEqual(open(os.path.join(repo, "Ext/mod.txt")).read(), "new\n")
        self.assertEqual(open(os.path.join(repo, "Ext/new.txt")).read(), "n\n")

    def test_identical_not_proposed_and_local_blocked(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/same.txt": "x\n", "Ext/mod.txt": "v2\n"},
            local={"Ext/mod.txt": "local\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/same.txt", "Ext/mod.txt"})
        by_path = {o.path: o for o in ops}
        self.assertEqual(by_path["Ext/same.txt"].status, "identica")
        self.assertEqual(by_path["Ext/mod.txt"].status, "bloqueada")
        self.assertTrue(any("modificacion_local" in b for b in by_path["Ext/mod.txt"].blockers))
        res = execute_operations(ops, authorized=True)
        self.assertEqual(open(os.path.join(repo, "Ext/mod.txt")).read(), "local\n")

    def test_untracked_dest_and_ignored(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_repo={"Ext/mod.txt": "untracked\n", "skip.log": "z\n"},
            ignore="*.log\n")
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"skip.log"})
        self.assertTrue(any(o.status == "bloqueada" for o in ops))

    def test_changed_after_analysis_blocks(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "Ext/mod.txt"), "v3\n")
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/mod.txt"})
        self.assertEqual(ops[0].status, "bloqueada")

    def test_path_escape_blocked(self):
        from gipler.report import Row
        rows = [Row("../evil.txt", "núcleo", "src_000000", "new_in_dev", "untracked", [])]
        dev = "/tmp/dev-escape-test"
        repo = "/tmp/repo-escape-test"
        for d in (dev, repo):
            os.makedirs(d, exist_ok=True)
        write(os.path.join(dev, "..", "evil.txt"), "x\n")
        ops = build_operations(rows, {("src_000000", "../evil.txt")}, dev, {"src_000000": repo}, {"dev": {}, "repos": {}})
        self.assertEqual(ops[0].status, "bloqueada")

    def test_symlink_internal_and_external(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/exec.sh": "#!/bin/bash\n"},
            links={"Ext/link_int": "exec.sh", "Ext/link_ext": "/etc/passwd"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/link_ext"})
        self.assertTrue(any("symlink_externo" in b for b in ops[0].blockers))

    def test_exec_bit_preserved_and_cancelled(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/exec.sh": "#!/bin/bash\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/exec.sh"})
        res = execute_operations(ops, authorized=False)
        self.assertEqual(res[0]["status"], "cancelada")
        self.assertFalse(os.path.exists(os.path.join(repo, "Ext/exec.sh")))
        res = execute_operations(ops, authorized=True)
        self.assertTrue(os.access(os.path.join(repo, "Ext/exec.sh"), os.X_OK))

    def test_mixed_selection(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/new.txt": "n\n", "Ext/mod.txt": "v2\n"},
            local={"Ext/mod.txt": "l\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/new.txt", "Ext/mod.txt"})
        res = execute_operations(ops, authorized=True)
        by = {r["path"]: r["status"] for r in res}
        self.assertEqual(by["Ext/new.txt"], "copiada")
        self.assertEqual(by["Ext/mod.txt"], "bloqueada")
        self.assertIn("Vista previa", preview(ops))

    def test_tui_prepare_then_authorize_only(self):
        from gipler.tui import ProfileState
        from gipler.profile import load_profile

        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/new.txt": "n\n"})
        self.addCleanup(tmp.cleanup)
        profile = load_profile(analysis.profile_id)
        st = ProfileState(profile, analysis)
        for r in rows:
            if r.path == "Ext/new.txt":
                st.selection.add((r.destination, r.path))
        ops = st.prepare()
        self.assertTrue(ops and ops[0].status == "copiable")
        self.assertFalse(os.path.exists(os.path.join(repo, "Ext/new.txt")))
        res = st.authorize_and_execute()
        self.assertTrue(os.path.exists(os.path.join(repo, "Ext/new.txt")))
        self.assertEqual(res[0]["status"], "copiada")

    def test_dest_created_after_analysis_not_overwritten(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/new.txt": "n\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/new.txt"})
        write(os.path.join(repo, "Ext/new.txt"), "intruso\n")
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertEqual(open(os.path.join(repo, "Ext/new.txt")).read(), "intruso\n")

    def test_dest_modified_after_analysis_not_overwritten(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/mod.txt"})
        write(os.path.join(repo, "Ext/mod.txt"), "otro\n")
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertEqual(open(os.path.join(repo, "Ext/mod.txt")).read(), "otro\n")

    def test_dest_symlink_after_analysis_blocked(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/mod.txt"})
        p = os.path.join(repo, "Ext/mod.txt")
        os.unlink(p)
        os.symlink("/etc/hostname", p)
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertTrue(os.path.islink(p))
        self.assertEqual(os.readlink(p), "/etc/hostname")

    def test_parent_dir_swapped_to_external_symlink(self):
        import shutil
        import tempfile

        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        write(os.path.join(outside, "mod.txt"), "outside\n")
        parent = os.path.join(repo, "Ext")
        shutil.rmtree(parent)
        os.symlink(outside, parent)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/mod.txt"})
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertEqual(open(os.path.join(outside, "mod.txt")).read(), "outside\n")

    def test_source_intact(self):
        tmp, dev, repo, rows, analysis, repos, sel = _setup(
            extra_dev={"Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, repo, rows, analysis, repos, {"Ext/mod.txt"})
        execute_operations(ops, authorized=True)
        self.assertEqual(open(os.path.join(dev, "Ext/mod.txt")).read(), "v2\n")


class WriteIntegrityTests(unittest.TestCase):
    """Integridad de la escritura del motor: nada de éxito con copias incompletas."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = os.path.join(self.tmp.name, "dev")
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)

    @staticmethod
    def _write(root, rel, content):
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as file:
            file.write(content)
        return path

    def _new_op(self, rel, content):
        src = self._write(self.dev, rel, content)
        row = Row(rel, "núcleo", "principal", "new_in_dev", "untracked", [])
        snapshot = {"dev": {rel: _sha(src)}, "repos": {"principal": {}}}
        ops = build_operations(
            [row], {("principal", rel)}, self.dev, {"principal": self.repo}, snapshot
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        return ops[0]

    def _existing_op(self, rel, src_content, dst_content):
        src = self._write(self.dev, rel, src_content)
        dst = self._write(self.repo, rel, dst_content)
        row = Row(rel, "núcleo", "principal", "modified_in_dev", "tracked_clean", [])
        snapshot = {
            "dev": {rel: _sha(src)},
            "repos": {"principal": {rel: _sha(dst)}},
        }
        ops = build_operations(
            [row], {("principal", rel)}, self.dev, {"principal": self.repo}, snapshot
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, "copiable")
        return ops[0]

    def test_full_write_with_real_files(self):
        content = b"contenido completo de integracion\n" * 100
        op = self._new_op("full.bin", content)
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        with open(os.path.join(self.repo, "full.bin"), "rb") as file:
            self.assertEqual(file.read(), content)

    def test_partial_write_requires_multiple_calls(self):
        content = b"A" * 1000
        op = self._new_op("partial.bin", content)
        real_write = os.write
        calls = []

        def partial(fd, data):
            calls.append(len(data))
            return real_write(fd, data[:7])

        with patch("os.write", side_effect=partial):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        self.assertGreater(len(calls), 1)
        with open(os.path.join(self.repo, "partial.bin"), "rb") as file:
            self.assertEqual(file.read(), content)

    def test_zero_byte_write_is_failure(self):
        op = self._new_op("zero.bin", b"datos")
        with patch("os.write", return_value=0):
            results = execute_operations([op], authorized=True)
        self.assertNotEqual(results[0]["status"], "copiada")
        self.assertEqual(results[0]["status"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "zero.bin")))

    def test_write_exception_is_failure(self):
        op = self._new_op("exc.bin", b"datos")
        with patch("os.write", side_effect=OSError("ENOSPC simulado")):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "exc.bin")))

    def test_existing_destination_failure_is_not_success(self):
        op = self._existing_op("existing.bin", b"nuevo", b"viejo")
        with patch("os.write", side_effect=OSError("ENOSPC simulado")):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "error")
        self.assertNotEqual(results[0]["status"], "copiada")

    def test_empty_file(self):
        op = self._new_op("empty.bin", b"")
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        self.assertEqual(os.path.getsize(os.path.join(self.repo, "empty.bin")), 0)

    def test_large_file_multiple_writes(self):
        content = os.urandom(1024 * 1024)
        op = self._new_op("large.bin", content)
        real_write = os.write
        calls = []

        def chunked(fd, data):
            calls.append(len(data))
            return real_write(fd, data[:65536])

        with patch("os.write", side_effect=chunked):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        self.assertGreater(len(calls), 1)
        with open(os.path.join(self.repo, "large.bin"), "rb") as file:
            self.assertEqual(file.read(), content)

    def test_incomplete_write_never_reports_success(self):
        op = self._new_op("incomplete.bin", b"x" * 500)
        real_write = os.write
        state = {"count": 0}

        def short_then_fail(fd, data):
            state["count"] += 1
            if state["count"] == 1:
                return real_write(fd, data[:5])
            raise OSError("fallo posterior")

        with patch("os.write", side_effect=short_then_fail):
            results = execute_operations([op], authorized=True)
        self.assertNotEqual(results[0]["status"], "copiada")
        self.assertEqual(results[0]["status"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "incomplete.bin")))

    def test_existing_destination_survives_write_failure(self):
        op = self._existing_op("keep.bin", b"nuevo", b"contenido anterior")
        with patch("os.write", side_effect=OSError("ENOSPC simulado")):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "error")
        with open(os.path.join(self.repo, "keep.bin"), "rb") as file:
            self.assertEqual(file.read(), b"contenido anterior")

    def test_new_destination_leaves_no_partial_on_failure(self):
        op = self._new_op("no-partial.bin", b"contenido")
        with patch("os.write", side_effect=OSError("ENOSPC simulado")):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "no-partial.bin")))

    def test_existing_destination_survives_fsync_failure(self):
        op = self._existing_op("keep-fsync.bin", b"nuevo", b"contenido anterior")
        real_fsync = os.fsync
        state = {"count": 0}

        def bad_fsync(fd):
            state["count"] += 1
            if state["count"] == 1:
                raise OSError("fsync simulado")
            return real_fsync(fd)

        with patch("os.fsync", side_effect=bad_fsync):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "error")
        with open(os.path.join(self.repo, "keep-fsync.bin"), "rb") as file:
            self.assertEqual(file.read(), b"contenido anterior")

    def test_existing_destination_survives_verification_failure(self):
        op = self._existing_op("keep-verify.bin", b"nuevo", b"contenido anterior")
        real_sha_fd = _sha_fd
        state = {"count": 0}

        def flaky_sha(fd):
            state["count"] += 1
            if state["count"] == 2:  # 1: destino, 2: verificación final
                return "0" * 64
            return real_sha_fd(fd)

        with patch("gipler.copy_engine._sha_fd", side_effect=flaky_sha):
            results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "error")
        with open(os.path.join(self.repo, "keep-verify.bin"), "rb") as file:
            self.assertEqual(file.read(), b"contenido anterior")

    def test_successful_replace_is_integral(self):
        op = self._existing_op("replace.bin", b"nuevo contenido", b"contenido anterior")
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        with open(os.path.join(self.repo, "replace.bin"), "rb") as file:
            self.assertEqual(file.read(), b"nuevo contenido")

    def test_symlink_destination_is_blocked(self):
        os.symlink("/etc/passwd", os.path.join(self.repo, "link.bin"))
        self._write(self.dev, "link.bin", b"contenido")
        row = Row("link.bin", "núcleo", "principal", "new_in_dev", "untracked", [])
        snapshot = {
            "dev": {"link.bin": _sha(os.path.join(self.dev, "link.bin"))},
            "repos": {"principal": {}},
        }
        op = build_operations(
            [row], {("principal", "link.bin")}, self.dev, {"principal": self.repo}, snapshot
        )[0]
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "bloqueada")
        self.assertTrue(os.path.islink(os.path.join(self.repo, "link.bin")))

    def test_permissions_are_applied_on_replace(self):
        self._write(self.dev, "perm.bin", b"nuevo")
        os.chmod(os.path.join(self.dev, "perm.bin"), 0o750)
        self._write(self.repo, "perm.bin", b"viejo")
        row = Row("perm.bin", "núcleo", "principal", "modified_in_dev", "tracked_clean", [])
        snapshot = {
            "dev": {"perm.bin": _sha(os.path.join(self.dev, "perm.bin"))},
            "repos": {"principal": {"perm.bin": _sha(os.path.join(self.repo, "perm.bin"))}},
        }
        op = build_operations(
            [row], {("principal", "perm.bin")}, self.dev, {"principal": self.repo}, snapshot
        )[0]
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        self.assertEqual(
            os.stat(os.path.join(self.repo, "perm.bin")).st_mode & 0o777, 0o750
        )


class HardLinkIntegrityTests(unittest.TestCase):
    """Los hard links del destino no deben modificarse al copiar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = os.path.join(self.tmp.name, "dev")
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.dev)
        os.makedirs(self.repo)

    def _write(self, root, rel, content):
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as file:
            file.write(content)
        return path

    def _op(self, rel, src_content, dst_content=None):
        src = self._write(self.dev, rel, src_content)
        if dst_content is not None:
            dst = self._write(self.repo, rel, dst_content)
            dst_hash = _sha(dst)
            axis_a = "modified_in_dev"
            axis_b = "tracked_clean"
        else:
            dst_hash = None
            axis_a = "new_in_dev"
            axis_b = "untracked"
        row = Row(rel, "núcleo", "principal", axis_a, axis_b, [])
        snapshot = {
            "dev": {rel: _sha(src)},
            "repos": {"principal": {rel: dst_hash} if dst_hash else {}},
        }
        ops = build_operations(
            [row], {("principal", rel)}, self.dev, {"principal": self.repo}, snapshot
        )
        self.assertEqual(len(ops), 1)
        return ops[0]

    def test_external_hard_link_not_modified(self):
        op = self._op("a.txt", b"NUEVO", b"ANTERIOR")
        outside = os.path.join(self.tmp.name, "externo.txt")
        os.link(os.path.join(self.repo, "a.txt"), outside)
        inode_before = os.lstat(os.path.join(self.repo, "a.txt")).st_ino
        with open(outside, "rb") as file:
            self.assertEqual(file.read(), b"ANTERIOR")

        results = execute_operations([op], authorized=True)

        self.assertEqual(results[0]["status"], "copiada")
        with open(os.path.join(self.repo, "a.txt"), "rb") as file:
            self.assertEqual(file.read(), b"NUEVO")
        with open(outside, "rb") as file:
            self.assertEqual(file.read(), b"ANTERIOR")
        self.assertNotEqual(os.lstat(os.path.join(self.repo, "a.txt")).st_ino, inode_before)
        self.assertFalse(os.path.samefile(os.path.join(self.repo, "a.txt"), outside))

    def test_multiple_hard_links_same_directory(self):
        op = self._op("b.txt", b"NUEVO", b"ANTERIOR")
        link1 = os.path.join(self.repo, "b_link1.txt")
        link2 = os.path.join(self.repo, "b_link2.txt")
        os.link(os.path.join(self.repo, "b.txt"), link1)
        os.link(os.path.join(self.repo, "b.txt"), link2)
        inode_before = os.lstat(os.path.join(self.repo, "b.txt")).st_ino
        self.assertEqual(os.lstat(os.path.join(self.repo, "b.txt")).st_nlink, 3)

        results = execute_operations([op], authorized=True)

        self.assertEqual(results[0]["status"], "copiada")
        with open(os.path.join(self.repo, "b.txt"), "rb") as file:
            self.assertEqual(file.read(), b"NUEVO")
        with open(link1, "rb") as file:
            self.assertEqual(file.read(), b"ANTERIOR")
        with open(link2, "rb") as file:
            self.assertEqual(file.read(), b"ANTERIOR")
        self.assertNotEqual(os.lstat(os.path.join(self.repo, "b.txt")).st_ino, inode_before)
        self.assertTrue(os.path.samefile(link1, link2))

    def test_normal_destination_has_nlink_one(self):
        op = self._op("c.txt", b"NUEVO", b"ANTERIOR")
        self.assertEqual(os.lstat(os.path.join(self.repo, "c.txt")).st_nlink, 1)
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        with open(os.path.join(self.repo, "c.txt"), "rb") as file:
            self.assertEqual(file.read(), b"NUEVO")

    def test_nonexistent_destination(self):
        op = self._op("d.txt", b"NUEVO")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "d.txt")))
        results = execute_operations([op], authorized=True)
        self.assertEqual(results[0]["status"], "copiada")
        with open(os.path.join(self.repo, "d.txt"), "rb") as file:
            self.assertEqual(file.read(), b"NUEVO")

    def test_reported_result_matches_physical_state(self):
        op = self._op("e.txt", b"NUEVO-CONTENIDO", b"ANTERIOR")
        results = execute_operations([op], authorized=True)
        reported = results[0]["status"]
        with open(os.path.join(self.repo, "e.txt"), "rb") as file:
            physical = file.read()
        self.assertEqual(reported, "copiada")
        self.assertEqual(physical, b"NUEVO-CONTENIDO")


if __name__ == "__main__":
    unittest.main()
