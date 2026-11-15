"""Helpers de test: repos Git temporales, totalmente en tmp."""
import os
import subprocess
import tempfile
import uuid


def git(repo, *args):
    subprocess.run(
        ["git", "-C", repo, *args],
        check=True, capture_output=True, text=True,
    )


def make_repo(base, name):
    path = os.path.join(base, name)
    os.makedirs(path)
    subprocess.run(["git", "init", "-q", path], check=True, capture_output=True)
    git(path, "config", "user.email", "test@test.local")
    git(path, "config", "user.name", "Test")
    return path


def write(path, content, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as f:
        f.write(content)
    if executable:
        os.chmod(path, 0o755)


def commit_all(repo, msg="init"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def dev_fixture(root, addons: dict):
    """Dev mínimo: addons dict name -> (status, [files], {path: content})."""
    dev = os.path.join(root, "dev")
    os.makedirs(dev, exist_ok=True)
    for name, (status, files, contents) in addons.items():
        header = (
            "# ============================================================\n"
            "# ADDON\n"
            "# ============================================================\n"
            f"# ID: {name}\n# NAME: {name}\n# VERSION: 0.1\n# STATUS: {status}\n"
            "# DESCRIPTION: test\n#\n# FILES:\n"
        )
        for rel in files:
            header += f"#   {rel}\n"
        header += "# ============================================================\n"
        write(os.path.join(dev, "addons", name, "cnfg.sh"), header, executable=True)
        for rel, content in contents.items():
            write(os.path.join(dev, *rel.split("/")), content)
    return dev


def tempdir():
    return tempfile.TemporaryDirectory()


def make_profile(root, work_files=None, sources=None, name="Perfil de prueba",
                 assignments=None):
    """Crea y guarda un perfil con un directorio de trabajo y fuentes de referencia.

    work_files: {relpath: content}
    sources: lista de dicts con:
        name, id, files={relpath: content}, git=bool, enabled=bool,
        acts_as_recognizer=bool, acts_as_destination=bool,
        sync_enabled=bool, sync_destination=str, kind=str, config=dict
    assignments: {relpath: source_id}

    Devuelve (profile, work_dir, roots).
    """
    from gipler.profile import Source, create_profile, save_profile

    work = os.path.join(root, "work")
    os.makedirs(work, exist_ok=True)
    for rel, content in (work_files or {}).items():
        write(os.path.join(work, *rel.split("/")), content)
    unique_name = f"{name} {os.getpid()}-{uuid.uuid4().hex[:8]}"
    profile = create_profile(unique_name, work)
    profile.sources = []
    roots = {}
    for index, spec in enumerate(sources or []):
        source_name = spec.get("name", f"src{index}")
        source_id = spec.get("id", f"src_{index:06d}")
        root_dir = os.path.join(root, f"ref_{source_name}")
        os.makedirs(root_dir, exist_ok=True)
        for rel, content in spec.get("files", {}).items():
            write(os.path.join(root_dir, *rel.split("/")), content)
        if spec.get("git", True):
            git(root_dir, "init", "-q")
            git(root_dir, "config", "user.email", "test@test.local")
            git(root_dir, "config", "user.name", "Test")
            if spec.get("files"):
                commit_all(root_dir)
        source = Source(
            id=source_id,
            name=source_name,
            kind=spec.get("kind", "reference_directory"),
            root=root_dir,
            enabled=spec.get("enabled", True),
            order=index,
            acts_as_recognizer=spec.get("acts_as_recognizer", True),
            acts_as_destination=spec.get("acts_as_destination", True),
            sync_enabled=spec.get("sync_enabled", True),
            sync_destination=spec.get("sync_destination", root_dir),
            config=spec.get("config", {}),
        )
        profile.sources.append(source)
        roots[source_id] = root_dir
    for rel, source_id in (assignments or {}).items():
        profile.assign_path(rel, source_id)
    save_profile(profile)
    return profile, work, roots


def make_profile_window(root, rows, sources=None, snapshot=None,
                        destination_roots=None, comparison_roots=None,
                        inventory_excluded=(), unassigned_new=(),
                        work_files=None, source_files=None, write_files=True,
                        derive_selection_keys=True):
    """Construye un GiplerWindow en modo perfil con filas arbitrarias.

    Adapta los tests GUI al modelo de perfiles: la ventana y todo el flujo
    son los reales; el análisis se parchea para proveer filas específicas.
    Devuelve (window, patcher); el llamador debe detener el patcher.
    """
    from unittest.mock import patch

    from gipler.gui.main_window import GiplerWindow
    from gipler.profile_analysis import ProfileAnalysis
    from gipler.workspace import WorkspaceInventory

    if sources is None:
        ids = sorted({row.destination for row in rows})
        sources = [{"id": sid, "name": sid, "files": {}} for sid in ids]
    profile, _work, _roots = make_profile(root, work_files=work_files, sources=sources)
    if derive_selection_keys:
        for row in rows:
            if getattr(row, "selection_key", None) is None:
                row.selection_key = (row.destination, row.path)
    for source in profile.sources:
        for rel, content in (source_files or {}).get(source.id, {}).items():
            write(os.path.join(source.root, *rel.split("/")), content)
    rows_by_source = {}
    for row in rows:
        rows_by_source.setdefault(row.destination, []).append(row)
    rows_by_source = {key: tuple(value) for key, value in rows_by_source.items()}
    analysis = ProfileAnalysis(
        profile_id=profile.id,
        work_dir=profile.work_dir,
        inventory=WorkspaceInventory(
            work_dir=profile.work_dir, included=(), excluded=tuple(inventory_excluded)
        ),
        entries=(),
        source_entries={},
        indeterminate=(),
        snapshot=snapshot or {"dev": {}, "repos": {}},
        destination_roots=destination_roots
        or {source.id: source.root for source in profile.sources},
        sources=tuple(profile.sources),
        rows_by_source=rows_by_source,
        comparison_roots=comparison_roots
        or {source.id: source.root for source in profile.sources},
        operation_rows=tuple(rows),
        unassigned_new=tuple(unassigned_new),
    )
    source_ids = {source.id for source in profile.sources}
    if write_files:
        for row in rows:
            if row.destination not in source_ids:
                continue
            path = os.path.join(profile.work_dir, *row.path.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                file.write(row.path)
            profile.assign_path(row.path, row.destination)
    patcher = patch("gipler.profile_analysis.analyze_profile", return_value=analysis)
    patcher.start()
    window = GiplerWindow(profile=profile)
    window.axis_a_box.setCurrentText("todos")
    for proxy in (window.proxy, window.repo_proxy):
        proxy.set_criteria(
            axis_a=None, axis_b=None, incidences=False, search="",
            owner="", exclude_identical=False,
        )
    window.expand_changes()
    return window, patcher
