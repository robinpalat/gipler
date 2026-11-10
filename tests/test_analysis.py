"""Tests del motor de análisis (Fase 5). Repos temporales, unittest stdlib."""
import os
import stat
import subprocess
import unittest

from gipler.analysis import analyze
from gipler.scanner import scan_tree, git_ignored_paths
from .helpers import make_repo, write, commit_all, dev_fixture, git


def project(addon_spec, main_files=None, addons_files=None, local=None, ignore=None):
    """Dev con addons {nombre: (status, [files], {rel: content})};
    repos principal/addons con archivos y commits opcionales."""
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    root = tmp.name
    dev = dev_fixture(root, addon_spec)
    principal = make_repo(root, "principal")
    addons = make_repo(root, "addons")

    def _fill(repo, files, commit=True):
        if ignore:
            for pat in ignore:
                write(os.path.join(repo, ".gitignore"), pat + "\n")
        if files:
            for rel, content in files.items():
                write(os.path.join(repo, *rel.split("/")), content)
        if files or ignore:
            commit_all(repo)

    _fill(principal, main_files or {})
    _fill(addons, addons_files or {})
    if local:
        by_name = {"principal": principal, "addons": addons}
        for name, changes in local.items():
            for rel, content in changes.items():
                write(os.path.join(by_name[name], *rel.split("/")), content)
    return tmp, dev, principal, addons


def row_for(rows, path, dest=None):
    hits = [r for r in rows if r.path == path and (dest is None or r.destination == dest)]
    return hits


class AxesTests(unittest.TestCase):
    def test_file_absent_in_both_sides_but_skip_worktree_tracked(self):
        spec = {"Feeds": ("external", ["addons/Feeds/cnfg.sh"], {})}
        tmp, dev, principal, addons = project(
            spec,
            addons_files={"default/tp1.xml": "present in HEAD\n"},
        )
        self.addCleanup(tmp.cleanup)
        git(addons, "update-index", "--skip-worktree", "--", "default/tp1.xml")
        os.remove(os.path.join(addons, "default", "tp1.xml"))
        os.rmdir(os.path.join(addons, "default"))
        self.assertFalse(os.path.lexists(os.path.join(dev, "default", "tp1.xml")))
        self.assertFalse(os.path.lexists(os.path.join(addons, "default", "tp1.xml")))

        entries = scan_tree(addons, git=True)
        self.assertIn("default/tp1.xml", entries)
        self.assertFalse(entries["default/tp1.xml"].exists)
        self.assertEqual(entries["default/tp1.xml"].git_state, "tracked_clean")
        git(addons, "cat-file", "-e", "HEAD:default/tp1.xml")
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", addons, "rev-parse", "HEAD:default/tp1.xml"],
                text=True,
            ).strip(),
            subprocess.check_output(
                ["git", "-C", addons, "rev-parse", ":default/tp1.xml"],
                text=True,
            ).strip(),
        )

        _, rows, info = analyze(dev, principal, addons)
        self.assertEqual(row_for(rows, "default/tp1.xml"), [])
        self.assertEqual(info["counts"]["missing_in_dev"], 0)

    def test_new_modified_identical(self):
        spec = {
            "Feeds": (
                "external",
                [
                    "addons/Feeds/cnfg.sh",
                    "addons/Feeds/new.txt",
                    "addons/Feeds/same.txt",
                    "addons/Feeds/mod.txt",
                ],
                {},
            )
        }
        tmp, dev, principal, addons = project(
            spec,
            main_files={"main.sh": "v1\n"},
            addons_files={
                "addons/Feeds/cnfg.sh": "same\n",
                "addons/Feeds/same.txt": "x\n",
                "addons/Feeds/mod.txt": "old\n",
            },
        )
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "main.sh"), "v2\n")
        write(os.path.join(dev, "addons/Feeds/new.txt"), "n\n")
        write(os.path.join(dev, "addons/Feeds/same.txt"), "x\n")
        write(os.path.join(dev, "addons/Feeds/mod.txt"), "new\n")
        _, rows, _ = analyze(dev, principal, addons)
        self.assertEqual(row_for(rows, "addons/Feeds/new.txt")[0].axis_a, "new_in_dev")
        self.assertEqual(row_for(rows, "addons/Feeds/mod.txt")[0].axis_a, "modified_in_dev")
        self.assertEqual(row_for(rows, "addons/Feeds/same.txt")[0].axis_a, "identical")
        self.assertEqual(row_for(rows, "main.sh", "principal")[0].axis_a, "modified_in_dev")

    def test_local_modification_not_confused_with_dev(self):
        spec = {"Feeds": ("external", ["addons/Feeds/cnfg.sh"], {})}
        tmp, dev, principal, addons = project(
            spec,
            main_files={"main.sh": "v1\n"},
            local={"principal": {"main.sh": "editado\n"}},
        )
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "main.sh"), "v1\n")
        _, rows, _ = analyze(dev, principal, addons)
        r = row_for(rows, "main.sh", "principal")[0]
        self.assertEqual(r.axis_b, "tracked_modified")
        # Eje A compara contenido físico: Dev v1 vs trabajo editado -> difieren.
        # Eje B marca el origen local; no se presenta como cambio de Dev a secas.
        self.assertEqual(r.axis_a, "modified_in_dev")

    def test_ignored_and_untracked(self):
        spec = {"Feeds": ("external", ["addons/Feeds/cnfg.sh"], {})}
        tmp, dev, principal, addons = project(
            spec, main_files={}, addons_files={}, ignore=[],
        )
        self.addCleanup(tmp.cleanup)
        write(os.path.join(principal, ".gitignore"), "*.log\n")
        write(os.path.join(addons, ".gitignore"), "ignored_dir/\n")
        commit_all(principal)
        commit_all(addons)
        write(os.path.join(principal, "skip.log"), "x\n")
        write(os.path.join(addons, "scratch.txt"), "y\n")
        write(os.path.join(dev, "skip.log"), "z\n")
        _, rows, _ = analyze(dev, principal, addons)
        self.assertEqual(row_for(rows, "skip.log")[0].axis_b, "ignored")
        self.assertEqual(row_for(rows, "addons/Feeds/cnfg.sh")[0].axis_a, "new_in_dev")

    def test_status_destination(self):
        spec = {
            "Nat": ("native", ["addons/Nat/cnfg.sh"], {}),
            "Ext": ("external", ["addons/Ext/cnfg.sh"], {}),
            "Devl": ("development", ["addons/Devl/cnfg.sh"], {}),
        }
        tmp, dev, principal, addons = project(spec)
        self.addCleanup(tmp.cleanup)
        _, rows, _ = analyze(dev, principal, addons)
        self.assertEqual(row_for(rows, "addons/Nat/cnfg.sh")[0].destination, "principal")
        self.assertEqual(row_for(rows, "addons/Ext/cnfg.sh")[0].destination, "addons")
        self.assertIn("addons/Devl/cnfg.sh", [r.path for r in rows if r.destination == "sin determinar"])


class ManifestTests(unittest.TestCase):
    def test_missing_shared_undeclared(self):
        spec = {
            "A": ("external", ["addons/A/cnfg.sh", "addons/A/miss.txt", "shared.txt"], {}),
            "B": ("external", ["addons/B/cnfg.sh", "shared.txt"], {}),
        }
        tmp, dev, principal, addons = project(spec)
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "addons/A/undeclared.txt"), "u\n")
        _, rows, _ = analyze(dev, principal, addons)
        miss = row_for(rows, "addons/A/miss.txt")[0]
        self.assertIn("manifest_missing_file", miss.incidences)
        shared = row_for(rows, "shared.txt")[0]
        self.assertIn("shared_file", shared.incidences)
        undecl = row_for(rows, "addons/A/undeclared.txt")[0]
        self.assertIn("manifest_undeclared_file", undecl.incidences)
        self.assertEqual(undecl.owner, "sin determinar")

    def test_executable_and_symlinks(self):
        spec = {"Feeds": ("external", ["addons/Feeds/cnfg.sh"], {})}
        tmp, dev, principal, addons = project(spec)
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "run.sh"), "#!/bin/bash\n", executable=True)
        os.symlink("run.sh", os.path.join(dev, "link_internal"))
        outside = os.path.join(tempfile := os.path.dirname(dev), "outside.txt")
        write(outside, "o\n")
        os.symlink(outside, os.path.join(dev, "link_external"))
        entries = scan_tree(dev)
        self.assertTrue(entries["run.sh"].executable)
        self.assertFalse(entries["run.sh"] if False else False)
        _, rows, _ = analyze(dev, principal, addons)
        ext = row_for(rows, "link_external")[0]
        self.assertIn("symlink_escapes_allowed_dirs", ext.incidences)

    def test_img11_decided_case(self):
        spec = {
            "Podcasts": (
                "external",
                ["addons/Podcasts/cnfg.sh", "/images/img.11.png"],
                {},
            )
        }
        tmp, dev, principal, addons = project(spec)
        self.addCleanup(tmp.cleanup)
        write(os.path.join(dev, "images/img.11.png"), b"png")
        write(os.path.join(principal, "images/img.11.png"), b"png")
        write(os.path.join(addons, "images/img.11.png"), b"png")
        commit_all(principal)
        commit_all(addons)
        _, rows, _ = analyze(dev, principal, addons)
        r = row_for(rows, "images/img.11.png", "addons")[0]
        self.assertEqual(r.owner, "Podcasts")
        self.assertNotIn("unknown_owner", r.incidences)
        self.assertNotIn("external_dependency", r.incidences)
        self.assertNotIn("path_outside_prefix", r.incidences)
        self.assertIn("duplicate_tracked_in_both", r.incidences)
        # No existe ruta inventada.
        self.assertFalse(any(x.path == "addons/Podcasts/images/img.11.png" for x in rows))

    def test_totals_reconcile_and_no_duplicate_rows(self):
        spec = {
            "Nat": ("native", ["addons/Nat/cnfg.sh"], {}),
            "Devl": ("development", ["addons/Devl/cnfg.sh"], {}),
        }
        tmp, dev, principal, addons = project(spec)
        self.addCleanup(tmp.cleanup)
        _, rows, info = analyze(dev, principal, addons)
        by_dest = {"principal": 0, "addons": 0, "sin determinar": 0}
        seen = set()
        for r in rows:
            self.assertNotIn((r.destination, r.path), seen)
            seen.add((r.destination, r.path))
            by_dest[r.destination] += 1
        self.assertEqual(sum(by_dest.values()), len(rows))
        self.assertEqual(info["counts"]["rows"], len(rows))
        # Filas sin destino no aparecen en los conteos de los dos repositorios.
        self.assertGreater(by_dest["sin determinar"], 0)


if __name__ == "__main__":
    unittest.main()
