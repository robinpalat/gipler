"""Helpers de test: repos Git temporales, totalmente en tmp."""
import os
import subprocess
import tempfile


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
