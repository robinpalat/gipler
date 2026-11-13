"""Read/write Git integration for a single physical reference directory.

The module is intentionally independent from Gipler's profile, recognition,
comparison, and copy state.  It only talks to the system ``git`` executable,
using argument lists (never a shell), and returns plain dataclasses that the
GUI can display.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, replace

DEFAULT_TIMEOUT = 120
STATUS_TIMEOUT = 30
DETECT_TIMEOUT = 15


class GitError(RuntimeError):
    """A Git command could not be executed or returned a failure."""

    def __init__(
        self,
        message: str,
        *,
        command: tuple[str, ...] = (),
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = None,
    ):
        super().__init__(message)
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@dataclass(frozen=True)
class GitRepository:
    path: str
    top_level: str


@dataclass(frozen=True)
class GitStatus:
    repository: str
    branch: str = ""
    oid: str = ""
    detached: bool = False
    upstream: str = ""
    ahead: int | None = None
    behind: int | None = None
    staged: int = 0
    modified: int = 0
    untracked: int = 0
    unmerged: int = 0
    remotes: tuple[str, ...] = ()
    remote_urls: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.staged or self.modified or self.untracked or self.unmerged)

    @property
    def has_remote(self) -> bool:
        return bool(self.remotes or self.remote_urls)

    @property
    def uses_https_remote(self) -> bool:
        return any(
            url.startswith(("https://", "http://")) for url in self.remote_urls
        )

    @property
    def uses_ssh_remote(self) -> bool:
        return any(
            url.startswith("ssh://") or (":" in url and "@" in url)
            for url in self.remote_urls
        )

    @property
    def summary(self) -> str:
        name = self.branch
        if not name:
            name = f"HEAD {self.oid[:7]}" if self.detached and self.oid else "sin rama"
        parts: list[str] = []
        if self.staged:
            parts.append(f"{self.staged} preparado{'s' if self.staged != 1 else ''}")
        if self.modified:
            parts.append(f"{self.modified} modificado{'s' if self.modified != 1 else ''}")
        if self.untracked:
            parts.append(f"{self.untracked} sin seguimiento")
        if self.unmerged:
            parts.append(f"{self.unmerged} conflicto{'s' if self.unmerged != 1 else ''}")
        if not parts:
            parts.append("limpio")
        if self.upstream:
            if self.ahead is not None and self.behind is not None:
                if self.ahead or self.behind:
                    parts.append(f"↑{self.ahead} ↓{self.behind}")
                else:
                    parts.append("al día")
        else:
            parts.append("sin remoto")
        return f"{name} · " + " · ".join(parts)


@dataclass(frozen=True)
class GitFileStatus:
    """Estado de un archivo dentro del repositorio Git."""

    path: str
    staged: bool = False
    unstaged: bool = False
    untracked: bool = False
    ignored: bool = False
    conflict: bool = False
    tracked_clean: bool = False

    @property
    def statuses(self) -> frozenset[str]:
        if self.conflict:
            return frozenset({"conflicts"})
        if self.untracked:
            return frozenset({"untracked"})
        if self.ignored:
            return frozenset({"ignored"})
        out: set[str] = set()
        if self.staged:
            out.add("staged")
        if self.unstaged:
            out.add("modified_unstaged")
        if self.tracked_clean:
            out.add("tracked_clean")
        return frozenset(out)

    @property
    def status_label(self) -> str:
        if self.conflict:
            return "Conflicto"
        if self.untracked:
            return "Sin seguimiento"
        if self.ignored:
            return "Ignorado"
        if self.staged and self.unstaged:
            return "Preparado y sin preparar"
        if self.staged:
            return "Preparado"
        if self.unstaged:
            return "Modificado sin preparar"
        if self.tracked_clean:
            return "Tracked sin cambios"
        return ""


@dataclass(frozen=True)
class GitOperationResult:
    kind: str
    repository: str
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    refresh_comparison: bool = False


def _git_executable() -> str | None:
    return shutil.which("git")


def _environment(optional_locks: bool = False, no_prompt: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    if optional_locks:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    if no_prompt:
        env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_sync(
    args: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("No se encontró el ejecutable Git en el sistema.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"Git no respondió en {timeout} segundos. La operación se detuvo."
        ) from exc


def detect_repository(
    path: str, *, timeout: int = DETECT_TIMEOUT
) -> GitRepository | None:
    """Return the repository rooted exactly at *path*, or ``None``.

    Both a normal ``.git`` directory and a gitfile (``.git`` file pointing to a
    separate git directory, as used by worktrees/submodules) are accepted.  A
    directory that merely contains an ordinary file called ``.git`` is not.
    """
    if not path:
        return None
    root = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(root):
        return None
    if not os.path.lexists(os.path.join(root, ".git")):
        return None
    git = _git_executable()
    if git is None:
        return None
    try:
        result = _run_sync(
            [git, "-C", root, "rev-parse", "--show-toplevel"],
            timeout=timeout,
            env=_environment(optional_locks=True),
        )
    except GitError:
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip().splitlines()
    if not top:
        return None
    top_level = top[-1].strip()
    try:
        if os.path.normcase(os.path.realpath(top_level)) != os.path.normcase(
            os.path.realpath(root)
        ):
            return None
    except OSError:
        return None
    return GitRepository(path=root, top_level=top_level)


def parse_status(
    repository: str,
    output: str,
    *,
    remotes: tuple[str, ...] = (),
    remote_urls: tuple[str, ...] = (),
) -> GitStatus:
    """Parse ``git status --porcelain=v2 --branch -z`` output."""
    branch = ""
    oid = ""
    detached = False
    upstream = ""
    ahead: int | None = None
    behind: int | None = None
    staged = modified = untracked = unmerged = 0

    for record in output.split("\0"):
        if not record:
            continue
        if record.startswith("# branch.oid "):
            oid = record[len("# branch.oid ") :].strip()
        elif record.startswith("# branch.head "):
            head = record[len("# branch.head ") :].strip()
            if head == "(detached)":
                detached = True
                branch = ""
            else:
                branch = head
        elif record.startswith("# branch.upstream "):
            upstream = record[len("# branch.upstream ") :].strip()
        elif record.startswith("# branch.ab "):
            for part in record[len("# branch.ab ") :].split():
                if part.startswith("+"):
                    try:
                        ahead = int(part[1:])
                    except ValueError:
                        ahead = None
                elif part.startswith("-"):
                    try:
                        behind = int(part[1:])
                    except ValueError:
                        behind = None
        elif record.startswith(("1 ", "2 ", "u ")):
            xy = record[2:4]
            if len(xy) != 2:
                continue
            x, y = xy[0], xy[1]
            if record.startswith("u "):
                unmerged += 1
                continue
            if x != ".":
                staged += 1
            if y != ".":
                modified += 1
        elif record.startswith("? "):
            untracked += 1

    return GitStatus(
        repository=repository,
        branch=branch,
        oid=oid,
        detached=detached,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        staged=staged,
        modified=modified,
        untracked=untracked,
        unmerged=unmerged,
        remotes=remotes,
        remote_urls=remote_urls,
    )


def git_status(repository: str, *, timeout: int = STATUS_TIMEOUT) -> GitStatus:
    """Read-only status for the repository rooted exactly at *repository*."""
    detected = detect_repository(repository)
    if detected is None:
        raise GitError("El directorio ya no es un repositorio Git válido.")
    git = _git_executable()
    if git is None:
        raise GitError("No se encontró el ejecutable Git en el sistema.")
    result = _run_sync(
        [
            git,
            "-C",
            detected.path,
            "status",
            "--porcelain=v2",
            "--branch",
            "--untracked-files=normal",
            "-z",
        ],
        timeout=timeout,
        env=_environment(optional_locks=True),
    )
    if result.returncode != 0:
        raise GitError(
            friendly_error("status", result.stderr, result.stdout, result.returncode),
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
    remotes, remote_urls = _read_remotes(git, detected.path, timeout=timeout)
    return parse_status(
        detected.path,
        result.stdout,
        remotes=remotes,
        remote_urls=remote_urls,
    )


def parse_remotes(output: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse ``git remote -v`` into unique names and URLs."""
    names: list[str] = []
    urls: list[str] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0] not in names:
            names.append(parts[0])
        if parts[1] not in urls:
            urls.append(parts[1])
    return tuple(names), tuple(urls)


def _read_remotes(
    git: str, repository: str, *, timeout: int = STATUS_TIMEOUT
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    result = _run_sync(
        [git, "-C", repository, "remote", "-v"],
        timeout=timeout,
        env=_environment(optional_locks=True),
    )
    if result.returncode != 0:
        return (), ()
    return parse_remotes(result.stdout)


def _read_file_list(
    git: str, repository: str, args: list[str], *, timeout: int = STATUS_TIMEOUT
) -> tuple[str, ...]:
    result = _run_sync(
        [git, "-C", repository, *args],
        timeout=timeout,
        env=_environment(optional_locks=True),
    )
    if result.returncode != 0:
        return ()
    return tuple(part for part in result.stdout.split("\0") if part)


def git_status_files(
    repository: str, *, timeout: int = STATUS_TIMEOUT
) -> list[GitFileStatus]:
    """List repository files with their Git status, without modifying them.

    Tracked files come from ``git ls-files``; ignored files are obtained
    explicitly with ``git ls-files --others --ignored``. The porcelain v2
    status supplies staged, unstaged, untracked and conflict states. A file
    with both staged and unstaged changes keeps both flags.
    """
    detected = detect_repository(repository)
    if detected is None:
        raise GitError("El directorio ya no es un repositorio Git válido.")
    git = _git_executable()
    if git is None:
        raise GitError("No se encontró el ejecutable Git en el sistema.")
    tracked = _read_file_list(git, detected.path, ["ls-files", "-z"], timeout=timeout)
    untracked = _read_file_list(
        git,
        detected.path,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        timeout=timeout,
    )
    ignored = _read_file_list(
        git,
        detected.path,
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        timeout=timeout,
    )
    result = _run_sync(
        [
            git,
            "-C",
            detected.path,
            "status",
            "--porcelain=v2",
            "--untracked-files=normal",
            "-z",
        ],
        timeout=timeout,
        env=_environment(optional_locks=True),
    )
    if result.returncode != 0:
        raise GitError(
            friendly_error("status", result.stderr, result.stdout, result.returncode),
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    by_path: dict[str, GitFileStatus] = {
        path: GitFileStatus(path=path, tracked_clean=True) for path in tracked
    }
    for path in untracked:
        by_path[path] = replace(
            by_path.get(path, GitFileStatus(path=path)),
            untracked=True,
            tracked_clean=False,
        )
    for path in ignored:
        by_path[path] = replace(
            by_path.get(path, GitFileStatus(path=path)),
            ignored=True,
            tracked_clean=False,
        )

    for record in result.stdout.split("\0"):
        if not record:
            continue
        if record.startswith(("1 ", "2 ")):
            parts = record.split(" ", 8)
            if len(parts) < 9:
                continue
            xy = parts[1]
            path = parts[8]
            if len(xy) != 2:
                continue
            x, y = xy[0], xy[1]
            if x in (".", "?") and y in (".", "?"):
                continue
            current = by_path.get(path, GitFileStatus(path=path))
            by_path[path] = replace(
                current,
                staged=(x != ".") or current.staged,
                unstaged=(y not in (".", "?")) or current.unstaged,
                tracked_clean=False,
            )
        elif record.startswith("u "):
            parts = record.split(" ", 10)
            if len(parts) < 11:
                continue
            path = parts[10]
            current = by_path.get(path, GitFileStatus(path=path))
            by_path[path] = replace(
                current, conflict=True, tracked_clean=False
            )
        elif record.startswith("? "):
            path = record[2:]
            current = by_path.get(path, GitFileStatus(path=path))
            by_path[path] = replace(
                current, untracked=True, tracked_clean=False
            )

    return [by_path[path] for path in sorted(by_path)]


def has_staged_changes(repository: str, *, timeout: int = STATUS_TIMEOUT) -> bool:
    """Return whether the index contains changes, without touching it."""
    git = _git_executable()
    if git is None:
        raise GitError("No se encontró el ejecutable Git en el sistema.")
    result = _run_sync(
        [git, "-C", repository, "diff", "--cached", "--name-only", "-z"],
        timeout=timeout,
        env=_environment(optional_locks=True),
    )
    if result.returncode != 0:
        raise GitError(
            friendly_error("commit", result.stderr, result.stdout, result.returncode),
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
    return bool(result.stdout.replace("\0", "").strip())


def validate_commit_message(message: str) -> str:
    clean = (message or "").strip()
    if not clean:
        raise GitError("El mensaje del commit no puede estar vacío.")
    return clean


def _operation_args(kind: str, message: str = "") -> list[str]:
    if kind == "fetch":
        return ["fetch"]
    if kind == "pull":
        return ["pull", "--ff-only"]
    if kind == "commit":
        return ["commit", "-m", validate_commit_message(message)]
    if kind == "push":
        return ["push"]
    raise ValueError(f"operación Git desconocida: {kind}")


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def friendly_error(
    kind: str, stderr: str = "", stdout: str = "", returncode: int | None = None
) -> str:
    """Translate common Git failures into actionable Spanish messages."""
    detail = (stderr or stdout or "").strip()
    low = detail.casefold()
    first = _first_line(detail)

    if "not a git repository" in low:
        return "El directorio ya no es un repositorio Git válido."
    if "safe.directory" in low:
        return (
            "Git rechazó el repositorio por seguridad (safe.directory). "
            "Revise la configuración de Git del usuario."
        )
    ssh_failure = (
        "permission denied (publickey" in low
        or "no such identity" in low
        or "host key verification failed" in low
        or "askpass" in low
        or "can't open display" in low
    )
    auth_failure = (
        "authentication failed" in low
        or "permission denied" in low
        or "could not read username" in low
        or "terminal prompts disabled" in low
    )
    connection_failure = (
        "could not resolve host" in low
        or "failed to connect" in low
        or "connection timed out" in low
        or "network is unreachable" in low
    )
    if kind in ("fetch", "pull", "push"):
        if ssh_failure:
            return (
                "No se pudo autenticar por SSH. Si la clave tiene passphrase, "
                "Gipler intenta mostrar un diálogo gráfico; también puede "
                "cargarla en ssh-agent o revisar la configuración SSH del usuario."
            )
        if auth_failure:
            return (
                "No se pudo autenticar con el remoto. "
                "Revise sus credenciales o su agente SSH."
            )
        if connection_failure:
            return "No se pudo conectar con el remoto. Revise la red o el remoto."
    if kind == "pull":
        if (
            "not possible to fast-forward" in low
            or "diverging branches" in low
            or "would be overwritten by merge" in low
        ):
            return (
                "Pull detenido: la rama no puede avanzar mediante fast-forward. "
                "No se hizo merge ni se descartaron cambios."
            )
        if (
            "local changes" in low
            or "please commit your changes or stash them" in low
            or "would be overwritten by" in low
        ):
            return (
                "Pull detenido: hay cambios locales que impiden la actualización. "
                "No se descartó ningún cambio."
            )
        if (
            "no tracking information" in low
            or "there is no tracking information" in low
            or "no such remote" in low
        ):
            return "Pull detenido: la rama actual no tiene una rama remota configurada."
    if kind == "push":
        if (
            "non-fast-forward" in low
            or "fetch first" in low
            or "[rejected]" in low
            or "failed to push some refs" in low
        ):
            return (
                "Push rechazado: el remoto tiene cambios que no están en local. "
                "No se hizo merge, rebase ni reset."
            )
        if (
            "no configured push destination" in low
            or "no upstream branch" in low
            or "has no upstream branch" in low
        ):
            return "Push detenido: la rama actual no tiene un remoto configurado."
    if kind == "commit":
        if "nothing to commit" in low:
            return "No hay archivos preparados para el commit."
        if "please tell me who you are" in low:
            return (
                "Git no tiene configurado user.name o user.email. "
                "Configúrelos antes de hacer el commit."
            )
    if first:
        return first
    return f"Git terminó con código {returncode if returncode is not None else 'desconocido'}."


def run_operation(
    repository: str,
    kind: str,
    *,
    message: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> GitOperationResult:
    """Run one of the four supported operations and never a destructive one."""
    if kind not in ("fetch", "pull", "commit", "push"):
        raise ValueError(f"operación Git desconocida: {kind}")
    detected = detect_repository(repository)
    if detected is None:
        return GitOperationResult(
            kind=kind,
            repository=repository,
            ok=False,
            message="El directorio ya no es un repositorio Git válido.",
            refresh_comparison=False,
        )
    try:
        args = _operation_args(kind, message)
    except GitError as exc:
        return GitOperationResult(
            kind=kind,
            repository=detected.path,
            ok=False,
            message=str(exc),
        )
    if kind == "commit":
        try:
            if not has_staged_changes(detected.path):
                return GitOperationResult(
                    kind="commit",
                    repository=detected.path,
                    ok=False,
                    message=(
                        "No hay archivos preparados para el commit. "
                        "Prepare archivos en el índice Git antes de confirmar."
                    ),
                )
        except GitError as exc:
            return GitOperationResult(
                kind="commit",
                repository=detected.path,
                ok=False,
                message=str(exc),
            )
    git = _git_executable()
    if git is None:
        return GitOperationResult(
            kind=kind,
            repository=detected.path,
            ok=False,
            message="No se encontró el ejecutable Git en el sistema.",
        )
    result = _run_sync(
        [git, "-C", detected.path, *args],
        timeout=timeout,
        env=_environment(no_prompt=True),
    )
    ok = result.returncode == 0
    message_text = (
        {
            "fetch": "Fetch completado.",
            "pull": "Pull completado.",
            "commit": "Commit creado.",
            "push": "Push completado.",
        }[kind]
        if ok
        else friendly_error(kind, result.stderr, result.stdout, result.returncode)
    )
    return GitOperationResult(
        kind=kind,
        repository=detected.path,
        ok=ok,
        message=message_text,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        refresh_comparison=ok and kind in ("pull", "commit"),
    )
