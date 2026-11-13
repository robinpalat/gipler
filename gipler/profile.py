"""Perfiles de Gipler: modelo, persistencia y CRUD.

Estructura en disco (un directorio por perfil, bajo el directorio de
configuración del usuario):

    ~/.config/Gipler/profiles/
        index.toml                    # schema, last_profile
        <id>/
            profile.toml              # schema, id, name, work_dir, [view], [[sources]]
            exclusions.toml           # [exclude] patterns=[...]  (mismo formato legado)

Reglas:
- Sólo se escribe en el directorio de configuración. Nunca en el árbol
  de trabajo del perfil ni en repositorios. Sin Git de escritura.
- Un archivo por perfil: renombrar/eliminar son operaciones aisladas.
- `exclusions.toml` reutiliza el formato de `ignore.toml`, de modo que
  las exclusiones de un perfil son un subconjunto de la misma sintaxis.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA = 1

# Tipos de fuente reconocidos hoy. Tipos futuros no están prohibidos:
# se guardan tal cual y la GUI los mostrará como "desconocido".
KNOWN_KINDS = (
    "reference_directory",
    "rules",
    "git_repository",
    "manifest",
    "debian_package",
)

DEFAULT_VIEW = {
    "theme": "oscuro",
    "home_view": "todo",
    "home_repository": "",
}

_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")


class ProfileError(ValueError):
    """Entrada inválida o fichero de perfil ilegible."""


# --------------------------------------------------------------- rutas
def profiles_root(override: str | None = None) -> str:
    """Directorio raíz de perfiles (acepta `override` para tests/CLI)."""
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.expanduser("~"), ".config", "Gipler", "profiles")


def index_path(root: str | None = None) -> str:
    return os.path.join(profiles_root(root), "index.toml")


def profile_dir(profile_id: str, root: str | None = None) -> str:
    return os.path.join(profiles_root(root), profile_id)


def profile_path(profile_id: str, root: str | None = None) -> str:
    return os.path.join(profile_dir(profile_id, root), "profile.toml")


def exclusions_path(profile_id: str, root: str | None = None) -> str:
    return os.path.join(profile_dir(profile_id, root), "exclusions.toml")


# --------------------------------------------------------------- modelo
@dataclass
class Source:
    """Fuente de reconocimiento y/o destino de sincronización (§5).

    Las dos funciones son independientes: una fuente puede reconocer sin
    recibir copias, o ser destino sin reconocer.
    """

    id: str
    name: str
    kind: str = "reference_directory"
    root: str = ""
    enabled: bool = True
    order: int = 0
    acts_as_recognizer: bool = True
    acts_as_destination: bool = False
    sync_destination: str = ""
    sync_enabled: bool = False
    destination_source_id: str = ""
    config: dict = field(default_factory=dict)
    baseline: SourceBaseline | None = None

    @property
    def is_destination(self) -> bool:
        return bool(self.acts_as_destination and self.enabled and self.sync_enabled)


@dataclass(frozen=True)
class BaselineEntry:
    path: str
    kind: str
    size: int
    mode: int
    sha256: str
    link_target: str = ""

    def as_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "kind": self.kind,
            "size": self.size,
            "mode": self.mode,
            "sha256": self.sha256,
            "link_target": self.link_target,
        }


@dataclass(frozen=True)
class SourceBaseline:
    established_at: str
    work_entries: tuple[BaselineEntry, ...]
    reference_entries: tuple[BaselineEntry, ...]
    destination_entries: tuple[BaselineEntry, ...]
    other_reference_paths: tuple[str, ...] = ()

    @property
    def work_paths(self) -> frozenset[str]:
        return frozenset(entry.path for entry in self.work_entries)

    @property
    def reference_paths(self) -> frozenset[str]:
        return frozenset(entry.path for entry in self.reference_entries)

    @property
    def destination_paths(self) -> frozenset[str]:
        return frozenset(entry.path for entry in self.destination_entries)

    @property
    def preexisting_reference_paths(self) -> frozenset[str]:
        return (
            self.reference_paths
            | self.destination_paths
            | frozenset(self.other_reference_paths)
        )


@dataclass
class Profile:
    id: str
    name: str
    work_dir: str
    created: str = ""
    sources: list[Source] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    view: dict = field(default_factory=lambda: dict(DEFAULT_VIEW))
    # Pertenencia decidida por el usuario: ruta relativa -> id de fuente.
    # Nunca implica copia ni sincronización; sólo reconocimiento explícito.
    assignments: dict[str, str] = field(default_factory=dict)

    # -- utilidades --------------------------------------------------
    def recognizers(self) -> list[Source]:
        return [s for s in self.sources if s.enabled and s.acts_as_recognizer]

    def destinations(self) -> list[Source]:
        return [s for s in self.sources if s.is_destination]

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def next_source_order(self) -> int:
        return max((s.order for s in self.sources), default=-1) + 1

    def add_source(self, source: Source) -> Source:
        if self.source(source.id) is not None:
            raise ProfileError(f"id de fuente duplicado: {source.id}")
        _validate_source(source, self)
        self.sources.append(source)
        self.sources.sort(key=lambda item: item.order)
        return source

    def remove_source(self, source_id: str) -> bool:
        """Retira la fuente del perfil. No toca ningún archivo en disco."""
        before = len(self.sources)
        self.sources = [s for s in self.sources if s.id != source_id]
        for source in self.sources:
            if source.destination_source_id == source_id:
                source.destination_source_id = ""
        self.assignments = {
            path: assigned
            for path, assigned in self.assignments.items()
            if assigned != source_id
        }
        self._normalize_source_order()
        return len(self.sources) != before

    def assign_path(self, path: str, source_id: str) -> str:
        """Registra la pertenencia explícita de una ruta a una referencia.

        Es una decisión de pertenencia: no copia, mueve ni sincroniza nada.
        """
        clean = _validate_relative_path(path)
        source = self.source(source_id)
        if source is None:
            raise ProfileError(f"no existe la referencia: {source_id}")
        if not source.enabled:
            raise ProfileError(f"la referencia está desactivada: {source.name}")
        if not source.acts_as_recognizer:
            raise ProfileError(
                f"la referencia no reconoce archivos: {source.name}"
            )
        self.assignments[clean] = source_id
        return clean

    def unassign_path(self, path: str) -> bool:
        clean = _validate_relative_path(path)
        return self.assignments.pop(clean, None) is not None

    def reorder_source(self, source_id: str, new_order: int) -> None:
        """Reordena una fuente sin cambiar su identidad ni configuración."""
        source = self.source(source_id)
        if source is None:
            raise ProfileError(f"no existe la fuente: {source_id}")
        if not isinstance(new_order, int) or new_order < 0:
            raise ProfileError(f"orden de fuente inválido: {new_order!r}")
        ordered = sorted(self.sources, key=lambda item: item.order)
        ordered.remove(source)
        ordered.insert(min(new_order, len(ordered)), source)
        for order, item in enumerate(ordered):
            item.order = order
        self.sources = ordered

    def _normalize_source_order(self) -> None:
        self.sources.sort(key=lambda item: item.order)
        for order, source in enumerate(self.sources):
            source.order = order


def new_source_id() -> str:
    return f"src_{uuid.uuid4().hex[:8]}"


def new_profile_id() -> str:
    return uuid.uuid4().hex[:12]


def make_profile(name: str, work_dir: str, profile_id: str | None = None) -> Profile:
    """Crea un perfil en memoria (no escribe)."""
    return Profile(
        id=profile_id or new_profile_id(),
        name=name,
        work_dir=_validate_work_dir(work_dir),
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        view=dict(DEFAULT_VIEW),
    )


def capture_source_baseline(
    work_dir: str,
    reference_dir: str,
    destination_dir: str | None = None,
    other_reference_dirs: tuple[str, ...] = (),
    established_at: str | None = None,
) -> SourceBaseline:
    """Capture read-only identities in Dev and one reference directory."""
    from .scanner import scan_tree

    work_root = os.path.abspath(os.path.expanduser(work_dir))
    reference_root = os.path.abspath(os.path.expanduser(reference_dir))
    destination_root = os.path.abspath(
        os.path.expanduser(destination_dir or reference_dir)
    )
    other_roots = tuple(
        dict.fromkeys(
            os.path.abspath(os.path.expanduser(path))
            for path in other_reference_dirs
            if os.path.isdir(os.path.expanduser(path))
        )
    )
    if not os.path.isdir(work_root):
        raise NotADirectoryError(work_root)
    if not os.path.isdir(reference_root):
        raise NotADirectoryError(reference_root)
    if not os.path.isdir(destination_root):
        raise NotADirectoryError(destination_root)

    def capture(root: str) -> tuple[BaselineEntry, ...]:
        content_entries = scan_tree(root, git=False)
        physical_entries: list[BaselineEntry] = []
        for current, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            dirnames[:] = sorted(name for name in dirnames if name != ".git")
            for name in sorted((*dirnames, *filenames)):
                absolute = os.path.join(current, name)
                relative = os.path.relpath(absolute, root).replace(os.sep, "/")
                metadata = os.lstat(absolute)
                content_entry = content_entries.get(relative)
                if stat.S_ISLNK(metadata.st_mode):
                    kind = "symlink"
                    link_target = os.readlink(absolute)
                elif stat.S_ISDIR(metadata.st_mode):
                    kind = "dir"
                    link_target = ""
                else:
                    kind = "file"
                    link_target = ""
                physical_entries.append(
                    BaselineEntry(
                        path=relative,
                        kind=kind,
                        size=metadata.st_size,
                        mode=metadata.st_mode & 0o777,
                        sha256=content_entry.sha256 if content_entry is not None else "",
                        link_target=link_target,
                    )
                )
                if kind == "symlink" and name in dirnames:
                    dirnames.remove(name)
        return tuple(
            sorted(physical_entries, key=lambda entry: entry.path)
        )

    reference_entries = capture(reference_root)
    destination_entries = (
        reference_entries
        if os.path.normcase(destination_root) == os.path.normcase(reference_root)
        else capture(destination_root)
    )
    own_roots = {
        os.path.normcase(work_root),
        os.path.normcase(reference_root),
        os.path.normcase(destination_root),
    }
    other_paths = {
        entry.path
        for root in other_roots
        if os.path.normcase(root) not in own_roots
        for entry in capture(root)
    }
    return SourceBaseline(
        established_at=established_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        work_entries=capture(work_root),
        reference_entries=reference_entries,
        destination_entries=destination_entries,
        other_reference_paths=tuple(sorted(other_paths)),
    )


# ---------------------------------------------------------- validación
def _validate_id(profile_id: str) -> None:
    if not profile_id or not _ID_RE.fullmatch(profile_id):
        raise ProfileError(f"id de perfil inválido: {profile_id!r}")


def _validate_name(name: str, root: str | None, except_id: str | None = None) -> str:
    clean = (name or "").strip()
    if not clean:
        raise ProfileError("el nombre del perfil no puede estar vacío")
    for existing in list_profiles(root):
        if existing.id != except_id and existing.name.strip().casefold() == clean.casefold():
            raise ProfileError(f"ya existe un perfil llamado: {clean}")
    return clean


def _validate_work_dir(work_dir: str) -> str:
    clean = (work_dir or "").strip()
    if not clean:
        raise ProfileError("el directorio de trabajo no puede estar vacío")
    if not os.path.isabs(os.path.expanduser(clean)):
        raise ProfileError(f"el directorio de trabajo debe ser absoluto: {clean!r}")
    return os.path.abspath(os.path.expanduser(clean))


def _validate_source_id(source_id: str) -> None:
    if not source_id or not _ID_RE.fullmatch(source_id):
        raise ProfileError(f"id de fuente inválido: {source_id!r}")


def _validate_relative_path(path: str) -> str:
    clean = (path or "").strip()
    if (
        not clean
        or clean.startswith("/")
        or any(part in ("", ".", "..") for part in clean.split("/"))
    ):
        raise ProfileError(f"ruta relativa inválida: {path!r}")
    return clean


def _validate_source(source: Source, profile: Profile | None = None) -> None:
    _validate_source_id(source.id)
    if not (source.name or "").strip():
        raise ProfileError("el nombre de la fuente no puede estar vacío")
    if profile is not None:
        clash = next(
            (s for s in profile.sources if s.id == source.id and s is not source), None
        )
        if clash is not None:
            raise ProfileError(f"id de fuente duplicado: {source.id}")


# ------------------------------------------------------- escritura TOML
def _esc(value: str) -> str:
    out = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{out}"'


def _val(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _esc(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_val(v) for v in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not _KEY_RE.fullmatch(str(key)):
                raise ProfileError(f"clave de configuración inválida: {key!r}")
        inner = ", ".join(f"{k} = {_val(v)}" for k, v in value.items())
        return "{ " + inner + " }" if inner else "{}"
    raise ProfileError(f"valor no soportado en TOML: {type(value).__name__}")


def _write_text(path: str, text: str) -> None:
    """Escritura atómica (temporal + rename) dentro del mismo directorio."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump_profile(profile: Profile) -> str:
    lines = [
        f"schema = {SCHEMA}",
        f"id = {_esc(profile.id)}",
        f"name = {_esc(profile.name)}",
        f"work_dir = {_esc(profile.work_dir)}",
        f"created = {_esc(profile.created)}",
        "",
        "[view]",
    ]
    for key in sorted(profile.view):
        lines.append(f"{key} = {_val(profile.view[key])}")
    for source in sorted(profile.sources, key=lambda s: s.order):
        lines += [
            "",
            "[[sources]]",
            f"id = {_esc(source.id)}",
            f"name = {_esc(source.name)}",
            f"kind = {_esc(source.kind)}",
            f"root = {_esc(source.root)}",
            f"enabled = {_val(bool(source.enabled))}",
            f"order = {_val(int(source.order))}",
            f"acts_as_recognizer = {_val(bool(source.acts_as_recognizer))}",
            f"acts_as_destination = {_val(bool(source.acts_as_destination))}",
            f"sync_destination = {_esc(source.sync_destination)}",
            f"sync_enabled = {_val(bool(source.sync_enabled))}",
            f"destination_source_id = {_esc(source.destination_source_id)}",
        ]
        if source.config:
            lines.append(f"config = {_val(dict(source.config))}")
        if source.baseline is not None:
            lines.append(
                f"baseline = {_val({
                    'established_at': source.baseline.established_at,
                    'work_entries': [
                        entry.as_dict() for entry in source.baseline.work_entries
                    ],
                    'reference_entries': [
                        entry.as_dict() for entry in source.baseline.reference_entries
                    ],
                    'destination_entries': [
                        entry.as_dict() for entry in source.baseline.destination_entries
                    ],
                    'other_reference_paths': list(
                        source.baseline.other_reference_paths
                    ),
                })}"
            )
    for path in sorted(profile.assignments):
        lines += [
            "",
            "[[assignments]]",
            f"path = {_esc(path)}",
            f"source_id = {_esc(profile.assignments[path])}",
        ]
    return "\n".join(lines) + "\n"


def dump_exclusions(patterns: list[str]) -> str:
    return "[exclude]\npatterns = [\n" + "".join(
        f'  "{p}",\n' for p in patterns
    ) + "]\n"


# ----------------------------------------------------------- lectura
def _load_toml(path: str) -> dict:
    if not os.path.isfile(path):
        raise ProfileError(f"no existe el fichero: {path}")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"TOML ilegible en {path}: {exc}") from exc


def _check_schema(data: dict, path: str) -> None:
    schema = data.get("schema")
    if not isinstance(schema, int):
        raise ProfileError(f"falta 'schema' en {path}")
    if schema > SCHEMA:
        raise ProfileError(
            f"el perfil {path} usa schema={schema}; esta versión sólo admite {SCHEMA}"
        )


def _load_baseline(raw: object, profile_id: str) -> SourceBaseline | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProfileError(f"línea de base inválida en la fuente del perfil {profile_id}")
    established_at = raw.get("established_at")
    if not isinstance(established_at, str) or not established_at.strip():
        raise ProfileError(f"fecha de línea de base inválida en el perfil {profile_id}")
    try:
        datetime.fromisoformat(established_at)
    except ValueError as exc:
        raise ProfileError(
            f"fecha de línea de base inválida en el perfil {profile_id}"
        ) from exc

    def entries_for(key: str) -> tuple[BaselineEntry, ...]:
        values = raw.get(key)
        if not isinstance(values, list):
            raise ProfileError(f"elementos de línea de base inválidos: {key}")
        entries: list[BaselineEntry] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, dict):
                raise ProfileError(f"elemento de línea de base inválido: {key}")
            path = value.get("path")
            kind = value.get("kind")
            size = value.get("size")
            mode = value.get("mode")
            sha256 = value.get("sha256")
            link_target = value.get("link_target", "")
            if (
                not isinstance(path, str)
                or not path
                or path.startswith("/")
                or any(part in ("", ".", "..") for part in path.split("/"))
                or path in seen
                or kind not in ("file", "dir", "symlink")
                or not isinstance(size, int)
                or size < 0
                or not isinstance(mode, int)
                or mode < 0
                or not isinstance(sha256, str)
                or not isinstance(link_target, str)
            ):
                raise ProfileError(f"elemento de línea de base inválido: {path!r}")
            seen.add(path)
            entries.append(BaselineEntry(path, kind, size, mode, sha256, link_target))
        return tuple(entries)

    reference_entries = entries_for("reference_entries")
    destination_entries = (
        entries_for("destination_entries")
        if "destination_entries" in raw
        else reference_entries
    )
    other_reference_paths = raw.get("other_reference_paths", [])
    if not isinstance(other_reference_paths, list) or any(
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or any(part in ("", ".", "..") for part in path.split("/"))
        for path in other_reference_paths
    ):
        raise ProfileError(
            f"rutas de otras referencias inválidas en el perfil {profile_id}"
        )
    return SourceBaseline(
        established_at=established_at,
        work_entries=entries_for("work_entries"),
        reference_entries=reference_entries,
        destination_entries=destination_entries,
        other_reference_paths=tuple(sorted(set(other_reference_paths))),
    )


def load_profile(profile_id: str, root: str | None = None) -> Profile:
    _validate_id(profile_id)
    path = profile_path(profile_id, root)
    data = _load_toml(path)
    _check_schema(data, path)
    if data.get("id") != profile_id:
        raise ProfileError(f"el id del fichero no coincide con el directorio: {path}")
    view = dict(DEFAULT_VIEW)
    view.update({k: v for k, v in (data.get("view") or {}).items()})
    sources = []
    for raw in data.get("sources") or []:
        source = Source(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            kind=str(raw.get("kind", "reference_directory")),
            root=str(raw.get("root", "")),
            enabled=bool(raw.get("enabled", True)),
            order=int(raw.get("order", 0)),
            acts_as_recognizer=bool(raw.get("acts_as_recognizer", True)),
            acts_as_destination=bool(raw.get("acts_as_destination", False)),
            sync_destination=str(raw.get("sync_destination", "")),
            sync_enabled=bool(raw.get("sync_enabled", False)),
            destination_source_id=str(raw.get("destination_source_id", "")),
            config=dict(raw.get("config") or {}),
            baseline=_load_baseline(raw.get("baseline"), profile_id),
        )
        _validate_source(source)
        sources.append(source)
    source_ids = {source.id for source in sources}
    for source in sources:
        if source.destination_source_id and source.destination_source_id not in source_ids:
            raise ProfileError(
                f"destino de fuente inexistente {source.destination_source_id!r} "
                f"en el perfil {profile_id}"
            )
    assignments: dict[str, str] = {}
    for raw in data.get("assignments") or []:
        if not isinstance(raw, dict):
            raise ProfileError(
                f"asignación inválida en el perfil {profile_id}"
            )
        relative = _validate_relative_path(str(raw.get("path", "")))
        assigned = str(raw.get("source_id", ""))
        if assigned not in source_ids:
            raise ProfileError(
                f"asignación a una referencia inexistente {assigned!r} "
                f"en el perfil {profile_id}"
            )
        if relative in assignments:
            raise ProfileError(
                f"asignación duplicada {relative!r} en el perfil {profile_id}"
            )
        assignments[relative] = assigned
    return Profile(
        id=profile_id,
        name=str(data.get("name", "")),
        work_dir=str(data.get("work_dir", "")),
        created=str(data.get("created", "")),
        sources=sources,
        exclusions=_load_exclusions(profile_id, root),
        view=view,
        assignments=assignments,
    )


def _load_exclusions(profile_id: str, root: str | None) -> list[str]:
    from .ignore import load_patterns

    path = exclusions_path(profile_id, root)
    if not os.path.isfile(path):
        return []
    return list(load_patterns(path))


def list_profiles(root: str | None = None) -> list[Profile]:
    """Perfiles ordenados por nombre. Un fichero corrupto no impide ver el resto."""
    base = profiles_root(root)
    if not os.path.isdir(base):
        return []
    out: list[Profile] = []
    for name in sorted(os.listdir(base)):
        if not os.path.isfile(os.path.join(base, name, "profile.toml")):
            continue
        try:
            out.append(load_profile(name, root))
        except ProfileError:
            continue
    out.sort(key=lambda p: p.name.strip().casefold())
    return out


def profile_exists(profile_id: str, root: str | None = None) -> bool:
    return os.path.isfile(profile_path(profile_id, root))


# ------------------------------------------------------------- índice
def _load_index(root: str | None) -> dict:
    path = index_path(root)
    if not os.path.isfile(path):
        return {"schema": SCHEMA, "last_profile": ""}
    data = _load_toml(path)
    _check_schema(data, path)
    return {
        "schema": SCHEMA,
        "last_profile": str(data.get("last_profile", "")),
    }


def last_profile_id(root: str | None = None) -> str | None:
    value = _load_index(root).get("last_profile") or ""
    return value or None


def set_last_profile_id(profile_id: str | None, root: str | None = None) -> None:
    if profile_id is not None and not profile_exists(profile_id, root):
        raise ProfileError(f"no existe el perfil: {profile_id}")
    data = {"schema": SCHEMA, "last_profile": profile_id or ""}
    _write_text(
        index_path(root),
        f"schema = {data['schema']}\nlast_profile = {_esc(data['last_profile'])}\n",
    )


# --------------------------------------------------------------- CRUD
def save_profile(profile: Profile, root: str | None = None) -> str:
    """Valida y persiste el perfil (profile.toml + exclusions.toml)."""
    _validate_id(profile.id)
    profile.name = _validate_name(profile.name, root, except_id=profile.id)
    profile.work_dir = _validate_work_dir(profile.work_dir)
    seen: set[str] = set()
    for source in profile.sources:
        _validate_source(source)
        if source.id in seen:
            raise ProfileError(f"id de fuente duplicado: {source.id}")
        seen.add(source.id)
    for source in profile.sources:
        if source.destination_source_id and source.destination_source_id not in seen:
            raise ProfileError(
                f"destino de fuente inexistente: {source.destination_source_id}"
            )
    for path, assigned in profile.assignments.items():
        _validate_relative_path(path)
        if assigned not in seen:
            raise ProfileError(f"asignación a una referencia inexistente: {assigned}")
    path = profile_path(profile.id, root)
    _write_text(path, dump_profile(profile))
    _write_text(exclusions_path(profile.id, root), dump_exclusions(profile.exclusions))
    return path


def create_profile(
    name: str, work_dir: str, root: str | None = None, profile_id: str | None = None
) -> Profile:
    profile = make_profile(name, work_dir, profile_id=profile_id)
    _validate_id(profile.id)
    if profile_exists(profile.id, root):
        raise ProfileError(f"ya existe el perfil: {profile.id}")
    save_profile(profile, root)
    return profile


def rename_profile(profile_id: str, new_name: str, root: str | None = None) -> Profile:
    profile = load_profile(profile_id, root)
    profile.name = _validate_name(new_name, root, except_id=profile_id)
    save_profile(profile, root)
    return profile


def delete_profile(profile_id: str, root: str | None = None) -> bool:
    """Elimina el directorio del perfil. Devuelve False si no existía."""
    _validate_id(profile_id)
    directory = profile_dir(profile_id, root)
    if not os.path.isdir(directory):
        return False
    for name in os.listdir(directory):
        target = os.path.join(directory, name)
        if os.path.isfile(target):
            os.unlink(target)
    os.rmdir(directory)
    if last_profile_id(root) == profile_id:
        set_last_profile_id(None, root)
    return True


def add_exclusion(profile_id: str, pattern: str, root: str | None = None) -> Profile:
    profile = load_profile(profile_id, root)
    clean = pattern.strip()
    if not clean:
        raise ProfileError("la exclusión no puede estar vacía")
    if clean not in profile.exclusions:
        profile.exclusions.append(clean)
        save_profile(profile, root)
    return profile


def remove_exclusion(profile_id: str, pattern: str, root: str | None = None) -> Profile:
    """Retira la regla de exclusión. No copia, mueve ni borra archivos."""
    profile = load_profile(profile_id, root)
    if pattern in profile.exclusions:
        profile.exclusions = [p for p in profile.exclusions if p != pattern]
        save_profile(profile, root)
    return profile
