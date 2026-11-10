"""Tests del motor de copia (solo directorios temporales)."""
import os
import unittest

from gipler.analysis import analyze
from gipler.copy_engine import build_operations, execute_operations, preview
from gipler.report import Row
from .helpers import make_repo, write, commit_all, dev_fixture


def _setup(extra_dev=None, extra_repo=None, local=None, ignore=None, links=None):
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    root = tmp.name
    files = [
        "addons/Ext/cnfg.sh",
        "addons/Ext/mod.txt",
        "addons/Ext/new.txt",
        "addons/Ext/same.txt",
        "addons/Ext/exec.sh",
        "addons/Ext/link_int",
        "addons/Ext/link_ext",
        "skip.log",
    ]
    spec = {"Ext": ("external", files, {})}
    dev = dev_fixture(root, spec)
    principal = make_repo(root, "principal")
    addons = make_repo(root, "addons")
    write(os.path.join(addons, "addons/Ext/cnfg.sh"), "x\n")
    write(os.path.join(addons, "addons/Ext/same.txt"), "x\n")
    write(os.path.join(addons, "addons/Ext/mod.txt"), "old\n")
    if ignore:
        write(os.path.join(addons, ".gitignore"), ignore)
    commit_all(addons)
    if local:
        for rel, c in local.items():
            write(os.path.join(addons, *rel.split("/")), c)
    if links:
        for rel, target in links.items():
            p = os.path.join(dev, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.symlink(target, p)
    if extra_dev:
        for rel, c in extra_dev.items():
            write(os.path.join(dev, *rel.split("/")), c, executable=(rel.endswith(".sh")))
    if extra_repo:
        for rel, c in extra_repo.items():
            write(os.path.join(addons, *rel.split("/")), c)
    _, rows, info = analyze(dev, principal, addons)
    repos = {"principal": principal, "addons": addons}
    def sel(paths):
        return {(r.destination, r.path) for r in rows if r.path in paths}
    return tmp, dev, addons, rows, info["meta"], info["snapshot"], repos, sel


def _ops(tmp, dev, addons, rows, meta, snap, repos, paths):
    selection = {(r.destination, r.path) for r in rows if r.path in paths}
    return build_operations(rows, selection, meta["dev"], repos, snap)


class CopyEngineTests(unittest.TestCase):
    def test_new_and_modified_copy(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/new.txt": "n\n", "addons/Ext/mod.txt": "new\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/new.txt", "addons/Ext/mod.txt"})
        self.assertTrue(all(o.status == "copiable" for o in ops), ops)
        res = execute_operations(ops, authorized=True)
        self.assertTrue(all(r["status"] == "copiada" for r in res), res)
        self.assertEqual(open(os.path.join(addons, "addons/Ext/mod.txt")).read(), "new\n")
        self.assertEqual(open(os.path.join(addons, "addons/Ext/new.txt")).read(), "n\n")

    def test_identical_not_proposed_and_local_blocked(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/same.txt": "x\n", "addons/Ext/mod.txt": "v2\n"},
            local={"addons/Ext/mod.txt": "local\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/same.txt", "addons/Ext/mod.txt"})
        by_path = {o.path: o for o in ops}
        self.assertEqual(by_path["addons/Ext/same.txt"].status, "identica")
        self.assertEqual(by_path["addons/Ext/mod.txt"].status, "bloqueada")
        self.assertTrue(any("modificacion_local" in b for b in by_path["addons/Ext/mod.txt"].blockers))
        res = execute_operations(ops, authorized=True)
        self.assertEqual(open(os.path.join(addons, "addons/Ext/mod.txt")).read(), "local\n")

    def test_untracked_dest_and_ignored(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_repo={"addons/Ext/mod.txt": "untracked\n", "skip.log": "z\n"},
            ignore="*.log\n")
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"skip.log"})
        self.assertTrue(any(o.status == "bloqueada" for o in ops))

    def test_changed_after_analysis_blocks(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "addons/Ext/mod.txt"), "v3\n")  # muta tras snapshot
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/mod.txt"})
        self.assertEqual(ops[0].status, "bloqueada")

    def test_path_escape_blocked(self):
        rows = [Row("../evil.txt", "núcleo", "principal", "new_in_dev", "untracked", [])]
        dev = "/tmp/dev-escape-test"; repo = "/tmp/repo-escape-test"
        for d in (dev, repo):
            os.makedirs(d, exist_ok=True)
        write(os.path.join(dev, "..", "evil.txt"), "x\n")
        ops = build_operations(rows, {("principal", "../evil.txt")}, dev, {"principal": repo}, {"dev": {}, "repos": {}})
        self.assertEqual(ops[0].status, "bloqueada")

    def test_symlink_internal_and_external(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/exec.sh": "#!/bin/bash\n"},
            links={"addons/Ext/link_int": "exec.sh", "addons/Ext/link_ext": "/etc/passwd"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/link_ext"})
        self.assertTrue(any("symlink_externo" in b for b in ops[0].blockers))

    def test_exec_bit_preserved_and_cancelled(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/exec.sh": "#!/bin/bash\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/exec.sh"})
        res = execute_operations(ops, authorized=False)
        self.assertEqual(res[0]["status"], "cancelada")
        self.assertFalse(os.path.exists(os.path.join(addons, "addons/Ext/exec.sh")))
        res = execute_operations(ops, authorized=True)
        self.assertTrue(os.access(os.path.join(addons, "addons/Ext/exec.sh"), os.X_OK))

    def test_mixed_selection(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/new.txt": "n\n", "addons/Ext/mod.txt": "v2\n"},
            local={"addons/Ext/mod.txt": "l\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/new.txt", "addons/Ext/mod.txt"})
        res = execute_operations(ops, authorized=True)
        by = {r["path"]: r["status"] for r in res}
        self.assertEqual(by["addons/Ext/new.txt"], "copiada")
        self.assertEqual(by["addons/Ext/mod.txt"], "bloqueada")
        self.assertIn("Vista previa", preview(ops))


    def test_tui_prepare_then_authorize_only(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/new.txt": "n\n"})
        self.addCleanup(tmp.cleanup)
        from gipler.tui import State
        st = State(rows, meta, [], snapshot=snap)
        for r in rows:
            if r.path == "addons/Ext/new.txt":
                st.selection.add((r.destination, r.path))
        ops = st.prepare()
        self.assertTrue(ops and ops[0].status == "copiable")
        self.assertFalse(os.path.exists(os.path.join(addons, "addons/Ext/new.txt")))
        res = st.authorize_and_execute()
        self.assertTrue(os.path.exists(os.path.join(addons, "addons/Ext/new.txt")))
        self.assertEqual(res[0]["status"], "copiada")


    def test_dest_created_after_analysis_not_overwritten(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/new.txt": "n\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/new.txt"})
        write(os.path.join(addons, "addons/Ext/new.txt"), "intruso\n")
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertEqual(open(os.path.join(addons, "addons/Ext/new.txt")).read(), "intruso\n")

    def test_dest_modified_after_analysis_not_overwritten(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/mod.txt"})
        write(os.path.join(addons, "addons/Ext/mod.txt"), "otro\n")
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertEqual(open(os.path.join(addons, "addons/Ext/mod.txt")).read(), "otro\n")

    def test_dest_symlink_after_analysis_blocked(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/mod.txt"})
        p = os.path.join(addons, "addons/Ext/mod.txt")
        os.unlink(p)
        os.symlink("/etc/hostname", p)
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertTrue(os.path.islink(p))
        self.assertEqual(os.readlink(p), "/etc/hostname")

    def test_parent_dir_swapped_to_external_symlink(self):
        import tempfile

        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        write(os.path.join(outside, "mod.txt"), "outside\n")
        parent = os.path.join(addons, "addons/Ext")
        import shutil as _sh
        _sh.rmtree(parent)
        os.symlink(outside, parent)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/mod.txt"})
        res = execute_operations(ops, authorized=True)
        self.assertEqual(res[0]["status"], "bloqueada")
        self.assertEqual(open(os.path.join(outside, "mod.txt")).read(), "outside\n")

    def test_source_intact(self):
        tmp, dev, addons, rows, meta, snap, repos, sel = _setup(
            extra_dev={"addons/Ext/mod.txt": "v2\n"})
        self.addCleanup(tmp.cleanup)
        ops = _ops(tmp, dev, addons, rows, meta, snap, repos, {"addons/Ext/mod.txt"})
        execute_operations(ops, authorized=True)
        self.assertEqual(open(os.path.join(dev, "addons/Ext/mod.txt")).read(), "v2\n")


if __name__ == "__main__":
    unittest.main()
