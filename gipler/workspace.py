"""Physical workspace inventory and exclusion provenance."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from .ignore import is_excluded


@dataclass(frozen=True)
class WorkspaceEntry:
    path: str
    kind: str
    size: int
    mode: int
    link_target: str = ""
    exclusion_rule: str = ""
    exclusion_inherited: bool = False

    @property
    def is_directory(self) -> bool:
        return self.kind == "directory"

    @property
    def is_excluded(self) -> bool:
        return bool(self.exclusion_rule)


@dataclass(frozen=True)
class WorkspaceInventory:
    work_dir: str
    included: tuple[WorkspaceEntry, ...]
    excluded: tuple[WorkspaceEntry, ...]


def scan_workspace(work_dir: str, exclusion_patterns: list[str] | None = None) -> WorkspaceInventory:
    """List physical files and directories without following symlinks."""
    root = os.path.abspath(os.path.expanduser(work_dir))
    if not os.path.isdir(root):
        raise NotADirectoryError(root)
    patterns = list(exclusion_patterns or ())
    included: list[WorkspaceEntry] = []
    excluded: list[WorkspaceEntry] = []

    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        candidates = [(name, True) for name in dirnames]
        candidates.extend((name, False) for name in filenames)
        candidates.sort(key=lambda item: (item[0].casefold(), item[0]))
        for name, listed_as_directory in candidates:
            absolute = os.path.join(current, name)
            relative = os.path.relpath(absolute, root).replace(os.sep, "/")
            metadata = os.lstat(absolute)
            is_link = stat.S_ISLNK(metadata.st_mode)
            if is_link:
                kind = "symlink"
                target = os.readlink(absolute)
            elif stat.S_ISDIR(metadata.st_mode):
                kind = "directory"
                target = ""
            else:
                kind = "file"
                target = ""

            rule = _exclusion_rule(relative, patterns)
            entry = WorkspaceEntry(
                path=relative,
                kind=kind,
                size=metadata.st_size,
                mode=metadata.st_mode & 0o777,
                link_target=target,
                exclusion_rule=rule or "",
                exclusion_inherited=bool(rule and not _matches_directly(relative, rule)),
            )
            (excluded if rule else included).append(entry)

            if listed_as_directory and is_link:
                dirnames.remove(name)

    key = lambda entry: (entry.path.casefold(), entry.path)
    return WorkspaceInventory(
        root,
        tuple(sorted(included, key=key)),
        tuple(sorted(excluded, key=key)),
    )


def _exclusion_rule(path: str, patterns: list[str]) -> str | None:
    matching = [pattern for pattern in patterns if is_excluded(path, [pattern])]
    if not matching:
        return None
    direct = [pattern for pattern in matching if _matches_directly(path, pattern)]
    return sorted(direct or matching, key=lambda pattern: (len(pattern), pattern))[0]


def _matches_directly(path: str, pattern: str) -> bool:
    normalized = pattern.rstrip("/")
    if path == normalized:
        return True
    return "/" not in normalized and path.rsplit("/", 1)[-1] == normalized
