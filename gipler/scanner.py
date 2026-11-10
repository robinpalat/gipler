"""Fase 1 — Scanner (Fase 1 del encargo, §5.1/§9 de la spec).

Recorre un árbol sin modificarlo y, para repos Git, deduce el estado Git
con comandos de solo lectura (git ls-files / git diff --name-only /
git check-ignore). Nunca ejecuta git add, commit, push ni checkout.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field

GIT_READONLY = [
    ["ls-files", "-z"],
    ["diff", "--name-only", "-z"],
    ["diff", "--cached", "--name-only", "-z"],
    ["check-ignore", "-z", "--stdin"],
]


@dataclass
class Entry:
    path: str  # relativa, posix
    exists: bool = True
    ftype: str = "file"  # file | symlink | dir
    size: int = 0
    mtime: float = 0.0
    sha256: str = ""
    mode: int = 0  # permisos ordinarios (st_mode & 0o777)
    link_target: str = ""  # solo si es symlink
    git_state: str = ""  # tracked_clean | tracked_modified | untracked | ignored
    # Desglose de tracked_modified (independiente de git_state):
    git_change: str = ""  # "" | contenido | permisos | contenido+permisos
    git_stage: str = ""   # "" | staged | unstaged | staged+unstaged

    @property
    def executable(self) -> bool:
        return bool(self.mode & 0o111)

    @property
    def is_symlink(self) -> bool:
        return self.ftype == "symlink"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_text(repo: str, args: list[str], stdin: str = "") -> str:
    try:
        r = subprocess.run(
            ["git", "-C", repo, *args],
            input=stdin, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _git_lines(repo: str, args: list[str], stdin: str = "") -> set[str]:
    out = _git_text(repo, args, stdin)
    return {x for x in out.split("\0") if x} if out else set()


def git_sets(repo: str) -> dict[str, set[str]]:
    """Conjuntos Git de solo lectura: tracked, modified, untracked, ignored."""
    tracked = _git_lines(repo, ["ls-files", "--cached", "-z"])
    tracked |= _git_lines(repo, ["ls-files", "--cached", "-z", "--others"])
    modified = _git_lines(repo, ["diff", "--name-only", "-z"]) | _git_lines(
        repo, ["diff", "--cached", "--name-only", "-z"]
    )
    untracked = _git_lines(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
    ignored = _git_lines(
        repo, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"]
    )
    return {
        "tracked": tracked,
        "modified": modified,
        "untracked": untracked,
        "ignored": ignored,
    }


def git_ignored_paths(repo: str, paths: list[str]) -> set[str]:
    """¿Qué rutas (incluso ausentes en disco) coinciden con .gitignore? (solo lectura)."""
    if not paths:
        return set()
    out = _git_text(repo, ["check-ignore", "-z", "--stdin"], "\0".join(paths))
    return {x for x in out.split("\0") if x}


def _git_raw(repo: str, args: list[str]) -> dict[str, tuple[str, str, str, str]]:
    """`git diff --raw` (solo lectura) -> path -> (oldmode, newmode, oldsha, newsha).

    Los renombres/copias (R/C) se ignoran: no se esperan en estos árboles y su
    formato de ruta no es unívoco sin `-z`.
    """
    out: dict[str, tuple[str, str, str, str]] = {}
    for line in _git_text(repo, args).splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 5 or not parts[0].startswith(":"):
            continue
        if parts[4][:1] in ("R", "C"):
            continue
        out[path] = (parts[0][1:], parts[1], parts[2], parts[3])
    return out


def _git_numstat(repo: str, args: list[str]) -> dict[str, tuple[str, str]]:
    """`git diff --numstat` (solo lectura) -> path -> (añadidas, borradas)."""
    out: dict[str, tuple[str, str]] = {}
    for line in _git_text(repo, args).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path = parts[2]
        if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
            path = path[1:-1]
        out[path] = (parts[0], parts[1])
    return out


def _is_content(a: str, b: str) -> bool:
    """numstat: `0 0` = solo cambio de modo; `- -` = binario con contenido."""
    if a == "-" or b == "-":
        return True
    return not (a == "0" and b == "0")


def git_change_details(repo: str) -> dict[str, tuple[str, str]]:
    """Desglose del pendiente Git respecto de HEAD (solo lectura, sin escrituras).

    path -> (cambio, fase) donde
      cambio: contenido | permisos | contenido+permisos
      fase:   staged | unstaged | staged+unstaged

    Combina `git diff --raw` / `--numstat` (índice ↔ árbol de trabajo) con
    `git diff --cached --raw` (HEAD ↔ índice).
    """
    unstaged: dict[str, list[bool]] = {}  # [contenido, permisos]
    staged: dict[str, list[bool]] = {}

    for path, (oldm, newm, _, _) in _git_raw(repo, ["diff", "--raw"]).items():
        slot = unstaged.setdefault(path, [False, False])
        if oldm != "000000" and newm != "000000" and oldm != newm:
            slot[1] = True
    for path, (a, b) in _git_numstat(repo, ["diff", "--numstat"]).items():
        if _is_content(a, b):
            unstaged.setdefault(path, [False, False])[0] = True

    for path, (oldm, newm, olds, news) in _git_raw(
        repo, ["diff", "--cached", "--raw"]
    ).items():
        slot = staged.setdefault(path, [False, False])
        if olds == "0000000" or news == "0000000":
            slot[0] = True  # alta/baja en el índice: es contenido, no un modo
        elif olds != news:
            slot[0] = True
        if oldm != "000000" and newm != "000000" and oldm != newm:
            slot[1] = True

    details: dict[str, tuple[str, str]] = {}
    for path in set(unstaged) | set(staged):
        u = unstaged.get(path, [False, False])
        s = staged.get(path, [False, False])
        content, mode = u[0] or s[0], u[1] or s[1]
        if not content and not mode:
            continue
        change = (
            "contenido+permisos" if content and mode
            else "contenido" if content
            else "permisos"
        )
        has_u, has_s = any(u), any(s)
        stage = "staged+unstaged" if has_u and has_s else "unstaged" if has_u else "staged"
        details[path] = (change, stage)
    return details


def scan_tree(root: str, git: bool = False) -> dict[str, Entry]:
    """Escanea root -> {path: Entry}. No sigue symlinks. No escribe nada."""
    entries: dict[str, Entry] = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            st = os.lstat(full)
            e = Entry(path=rel)
            if os.path.islink(full):
                e.ftype = "symlink"
                e.link_target = os.readlink(full)
                e.sha256 = hashlib.sha256(
                    ("symlink:" + e.link_target).encode()
                ).hexdigest()
            else:
                e.ftype = "file"
            e.size = st.st_size
            e.mtime = st.st_mtime
            e.mode = st.st_mode & 0o777
            if e.ftype == "file":
                try:
                    e.sha256 = _sha256_file(full)
                except OSError:
                    e.sha256 = ""
            entries[rel] = e
    if git:
        sets = git_sets(root)
        details = git_change_details(root)
        all_paths = set(entries) | sets["tracked"]
        # Archivos trackeados pero borrados en disco (no encontrados por walk):
        for p in sorted(all_paths - set(entries)):
            e = Entry(path=p, exists=False, ftype="file")
            entries[p] = e
        # Estado B para entradas presentes en disco:
        for p, e in entries.items():
            if p in sets["ignored"]:
                e.git_state = "ignored"
            elif p in sets["untracked"]:
                e.git_state = "untracked"
            elif p in sets["tracked"]:
                e.git_state = "tracked_modified" if p in sets["modified"] else "tracked_clean"
            else:
                e.git_state = "untracked"
            if p in details:
                e.git_change, e.git_stage = details[p]
    return entries


def git_state_for_absent(repo: str, path: str) -> str:
    """Estado B de una ruta ausente en el repo: ignored si coincide con
    .gitignore, untracked en caso contrario."""
    return "ignored" if path in git_ignored_paths(repo, [path]) else "untracked"


def git_states_for_absent(repo: str, paths: list[str]) -> dict[str, str]:
    ignored = git_ignored_paths(repo, paths)
    return {p: ("ignored" if p in ignored else "untracked") for p in paths}


def symlink_scope(dev_root: str, rel: str, entry: Entry) -> str:
    """'internal' si el destino resuelto queda dentro de dev_root, 'external'
    si sale, 'none' si no es symlink (spec §7.8)."""
    if not entry.is_symlink:
        return "none"
    dev_root = os.path.abspath(dev_root)
    resolved = os.path.normpath(os.path.join(dev_root, os.path.dirname(rel), entry.link_target))
    if resolved == dev_root or resolved.startswith(dev_root + os.sep):
        return "internal"
    return "external"
