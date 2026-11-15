"""Profile analysis adapted to Gipler's shared scanner/comparator/report model."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import scanner
from .comparator import compare_pair
from .copy_policy import (
    entry_copy_blockers,
    entry_copy_decisions,
    entry_copy_status,
)
from .profile import BaselineEntry, BaselineStatus, Profile, Source
from .recognition import (
    MembershipState,
    RecognitionClaim,
    RecognitionResult,
    collect_claims,
    resolve_claims,
)
from .report import Row
from .selection import (
    make_selection_key,
    selection_key_for_candidates,
)
from .workspace import WorkspaceEntry, WorkspaceInventory, scan_workspace


@dataclass(frozen=True)
class BaselineMatch:
    """Coincidencia histórica de una ruta con un snapshot de línea de base."""

    source_id: str
    role: str
    root: str
    path: str
    content: str
    entry: BaselineEntry | None = None

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.source_id, self.role, self.root, self.path


@dataclass(frozen=True)
class ProfileEntry:
    physical: WorkspaceEntry
    membership: RecognitionResult
    comparisons: dict[str, str]
    destination_git_states: dict[str, str]
    work_dir: str
    destination_comparisons: dict[str, str] = field(default_factory=dict)
    reference_git_states: dict[str, str] = field(default_factory=dict)
    post_baseline_new: bool = False
    baseline_status: BaselineStatus | None = None
    baseline_matches: tuple[BaselineMatch, ...] = ()
    content_matches_elsewhere: tuple[BaselineMatch, ...] = ()

    @property
    def path(self) -> str:
        return self.physical.path

    @property
    def kind(self) -> str:
        return self.physical.kind

    @property
    def eligible_destination_source_id(self) -> str | None:
        eligible = self.eligible_destination_source_ids
        return eligible[0] if len(eligible) == 1 else None

    @property
    def copy_decisions(self):
        return entry_copy_decisions(self)

    @property
    def copy_blockers(self) -> tuple[str, ...]:
        return entry_copy_blockers(self)

    @property
    def copy_status(self) -> str:
        return entry_copy_status(self)

    @property
    def eligible_destination_source_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.destination_id
            for decision in self.copy_decisions
            if decision.eligible
        )

    @property
    def is_unassigned_new(self) -> bool:
        """Nuevo aparecido tras la línea de base y aún sin referencia asignada."""
        return (
            self.post_baseline_new
            and self.membership.state == MembershipState.UNKNOWN
            and self.physical.kind != "directory"
        )


@dataclass(frozen=True)
class ProfileAnalysis:
    profile_id: str
    work_dir: str
    inventory: WorkspaceInventory
    entries: tuple[ProfileEntry, ...]
    source_entries: dict[str, tuple[ProfileEntry, ...]]
    indeterminate: tuple[ProfileEntry, ...]
    snapshot: dict
    destination_roots: dict[str, str]
    sources: tuple[Source, ...]
    rows_by_source: dict[str, tuple[Row, ...]] = field(default_factory=dict)
    comparison_roots: dict[str, str] = field(default_factory=dict)
    operation_rows: tuple[Row, ...] = ()
    # Archivos aparecidos tras la línea de base y aún sin referencia asignada.
    unassigned_new: tuple[ProfileEntry, ...] = ()
    # Entradas excluidas: conservan reconocimiento y pertenencia, pero no
    # participan en las colecciones operativas (filas, operaciones, revisión).
    excluded_entries: tuple[ProfileEntry, ...] = ()

    def copy_rows(self) -> list[Row]:
        """Return rows for the existing guarded copy engine, never an alternate engine."""
        return list(self.operation_rows)

    @property
    def membership_review_entries(self) -> tuple[ProfileEntry, ...]:
        """Files with unknown, ambiguous, or valid shared membership for UI review."""
        entries = {
            entry.path: entry
            for entry in self.indeterminate
        }
        entries.update(
            {
                entry.path: entry
                for entry in self.entries
                if entry.membership.state == MembershipState.SHARED
            }
        )
        return tuple(entries[path] for path in sorted(entries))


def _is_git_root(root: str, source: Source) -> bool:
    return source.kind == "git_repository" or os.path.lexists(os.path.join(root, ".git"))


def _git_state(
    entry: scanner.Entry | None,
    git_root: bool,
    root: str,
    path: str,
) -> str:
    if not git_root:
        return "n/a"
    if entry is not None:
        return entry.git_state
    return scanner.git_state_for_absent(root, path)


def _recognition_for_path(
    path: str,
    profile: Profile,
    reference_entries: dict[str, dict[str, scanner.Entry]],
    baseline_reference_paths: dict[str, frozenset[str]],
) -> RecognitionResult:
    sources_by_id = {source.id: source for source in profile.sources}
    assigned_id = profile.assignments.get(path)
    if assigned_id:
        assigned = sources_by_id.get(assigned_id)
        if (
            assigned is not None
            and assigned.enabled
            and assigned.acts_as_recognizer
        ):
            # La pertenencia decidida por el usuario tiene prioridad: nunca se
            # contradice ni se reparte automáticamente entre otras referencias.
            return resolve_claims([RecognitionClaim(assigned_id)], profile.sources)
    claims = list(collect_claims(path, profile.sources))
    claimed_ids = {claim.source_id for claim in claims}
    for source_id, entries in reference_entries.items():
        entry = entries.get(path)
        source = sources_by_id.get(source_id)
        if (
            source is not None
            and source.enabled
            and source.acts_as_recognizer
            and source_id not in claimed_ids
            and entry is not None
            and not entry.exists
            and entry.git_state in ("tracked_clean", "tracked_modified")
        ):
            claims.append(RecognitionClaim(source_id))
    for source in profile.sources:
        if (
            source.enabled
            and source.acts_as_recognizer
            and source.kind == "reference_directory"
            and source.baseline is not None
            and path in baseline_reference_paths[source.id]
        ):
            claims.append(RecognitionClaim(source.id))
    return resolve_claims(claims, profile.sources)


def _permission_difference(dev_entry: scanner.Entry | None, ref_entry: scanner.Entry | None) -> str:
    if (
        dev_entry is None
        or ref_entry is None
        or not dev_entry.exists
        or not ref_entry.exists
        or dev_entry.is_symlink
        or ref_entry.is_symlink
        or dev_entry.mode == ref_entry.mode
    ):
        return ""
    text = f"{oct(dev_entry.mode)[2:]}→{oct(ref_entry.mode)[2:]}"
    if bool(dev_entry.mode & 0o111) != bool(ref_entry.mode & 0o111):
        text += " · bit ejecutable"
    return text


_CONTENT_SAME = "same"
_CONTENT_MODIFIED = "modified"
_CONTENT_UNKNOWN = "unknown"


def _current_content(
    dev_entry: scanner.Entry | None,
    physical: WorkspaceEntry | None,
) -> tuple[str, str, str]:
    """Devuelve (kind, sha256, link_target) de la identidad presente en work."""
    if dev_entry is not None and dev_entry.exists:
        if dev_entry.is_symlink:
            return "symlink", dev_entry.sha256, dev_entry.link_target
        return "file", dev_entry.sha256, ""
    if physical is not None and physical.kind == "directory":
        return "dir", "", ""
    if physical is not None and physical.kind == "symlink":
        return "symlink", "", physical.link_target
    if physical is not None and physical.kind == "file":
        return "file", "", ""
    return "file", "", ""


def _baseline_content_state(
    entry: BaselineEntry | None,
    current_kind: str,
    current_sha256: str,
    current_link_target: str,
) -> str:
    """Compara contenido respetando tipo: SHA, link_target o kind."""
    if entry is None:
        return _CONTENT_UNKNOWN
    if current_kind == "dir":
        return _CONTENT_SAME if entry.kind == "dir" else _CONTENT_MODIFIED
    if current_kind == "symlink":
        if entry.kind != "symlink":
            return _CONTENT_MODIFIED
        return (
            _CONTENT_SAME
            if current_link_target == entry.link_target
            else _CONTENT_MODIFIED
        )
    if entry.kind != "file":
        return _CONTENT_MODIFIED
    if not current_sha256 or not entry.sha256:
        return _CONTENT_UNKNOWN
    return (
        _CONTENT_SAME
        if current_sha256 == entry.sha256
        else _CONTENT_MODIFIED
    )


def _baseline_content_key(entry: BaselineEntry) -> tuple[str, str] | None:
    if entry.kind == "file" and entry.sha256:
        return "file", entry.sha256
    if entry.kind == "symlink":
        return "symlink", entry.link_target
    return None


def _aggregate_baseline_status(matches: tuple[BaselineMatch, ...]) -> BaselineStatus | None:
    if not matches:
        return BaselineStatus.NEW
    contents = {match.content for match in matches}
    if _CONTENT_SAME in contents:
        return BaselineStatus.KNOWN_SAME
    if _CONTENT_MODIFIED in contents:
        return BaselineStatus.KNOWN_MODIFIED
    return BaselineStatus.KNOWN


def _baseline_index(profile: Profile) -> tuple[
    int,
    dict[str, list[tuple[str, str, str, BaselineEntry | None]]],
    dict[tuple[str, str], list[tuple[str, str, str, BaselineEntry]]],
]:
    """Índice único de antecedentes; no duplica la clasificación por ruta.

    Incluye todas las fuentes con baseline válida, habilitadas o no. Las
    coincidencias se conservan separadas para no colapsar raíces distintas.
    """
    by_path: dict[str, list[tuple[str, str, str, BaselineEntry | None]]] = {}
    content_index: dict[
        tuple[str, str], list[tuple[str, str, str, BaselineEntry]]
    ] = {}
    relevant = 0
    for source in profile.sources:
        baseline = source.baseline
        if baseline is None:
            continue
        relevant += 1
        sections = (
            (source.id, "work", baseline.work_root, baseline.work_entries),
            (source.id, "reference", baseline.reference_root, baseline.reference_entries),
            (
                source.id,
                "destination",
                baseline.destination_root,
                baseline.destination_entries,
            ),
        )
        for source_id, role, root, entries in sections:
            for entry in entries:
                by_path.setdefault(entry.path, []).append(
                    (source_id, role, root, entry)
                )
                key = _baseline_content_key(entry)
                if key is not None:
                    content_index.setdefault(key, []).append(
                        (source_id, role, root, entry)
                    )
        covered = set()
        for snapshot in baseline.other_references:
            for entry in snapshot.entries:
                covered.add(entry.path)
                by_path.setdefault(entry.path, []).append(
                    (snapshot.source_id, snapshot.role, snapshot.root, entry)
                )
                key = _baseline_content_key(entry)
                if key is not None:
                    content_index.setdefault(key, []).append(
                        (snapshot.source_id, snapshot.role, snapshot.root, entry)
                    )
        for path in baseline.other_reference_paths:
            if path in covered:
                continue
            by_path.setdefault(path, []).append(
                (source.id, "other", "", None)
            )
    return relevant, by_path, content_index


def _baseline_matches_for_path(
    path: str,
    raw_matches: list[tuple[str, str, str, BaselineEntry | None]],
    current_kind: str,
    current_sha256: str,
    current_link_target: str,
) -> tuple[BaselineMatch, ...]:
    matches: list[BaselineMatch] = []
    for source_id, role, root, entry in raw_matches:
        matches.append(
            BaselineMatch(
                source_id=source_id,
                role=role,
                root=root,
                path=path,
                content=_baseline_content_state(
                    entry,
                    current_kind,
                    current_sha256,
                    current_link_target,
                ),
                entry=entry,
            )
        )
    return tuple(matches)


def _content_matches_elsewhere(
    path: str,
    current_kind: str,
    current_sha256: str,
    current_link_target: str,
    content_index: dict[
        tuple[str, str], list[tuple[str, str, str, BaselineEntry]]
    ],
) -> tuple[BaselineMatch, ...]:
    if current_kind == "file" and current_sha256:
        key = ("file", current_sha256)
    elif current_kind == "symlink":
        key = ("symlink", current_link_target)
    else:
        return ()
    matches: list[BaselineMatch] = []
    for source_id, role, root, entry in content_index.get(key, ()):
        if entry.path == path:
            continue
        matches.append(
            BaselineMatch(
                source_id=source_id,
                role=role,
                root=root,
                path=entry.path,
                content=_CONTENT_SAME,
                entry=entry,
            )
        )
    return tuple(matches)


def _entry_row(
    entry: ProfileEntry,
    source: Source,
    comparison: str,
    git_state: str,
    ref_entry: scanner.Entry | None,
    dev_entry: scanner.Entry | None,
    selection_key: tuple[str, str] | None = None,
    copy_blockers: tuple[str, ...] = (),
    copy_status: str = "",
) -> Row:
    incidences: list[str] = []
    if entry.membership.state == MembershipState.SHARED:
        incidences.append("shared_file")
    elif entry.membership.state == MembershipState.AMBIGUOUS:
        incidences.append("ambiguous")
    incidences.extend(entry.membership.reasons)
    if entry.physical.kind == "symlink" and dev_entry is not None:
        if scanner.symlink_scope(entry.work_dir, entry.path, dev_entry) == "external":
            incidences.append("symlink_escapes_allowed_dirs")
    owner = source.name
    row = Row(
        entry.path,
        owner,
        source.id,
        comparison or "n/a",
        git_state or "n/a",
        incidences,
        git_change=ref_entry.git_change if ref_entry is not None else "",
        git_stage=ref_entry.git_stage if ref_entry is not None else "",
        perm=_permission_difference(dev_entry, ref_entry),
        selection_key=selection_key,
        copy_blockers=copy_blockers,
        copy_status=copy_status,
    )
    row.post_baseline_new = entry.post_baseline_new
    return row


def analyze_profile(profile: Profile) -> ProfileAnalysis:
    """Run the original scanner/comparator semantics over configured references.

    The physical workspace inventory remains the source for Inicio. Reference tabs
    are comparison results and include reference-only paths as ``missing_in_dev``.
    """
    inventory = scan_workspace(profile.work_dir, profile.exclusions)
    work_root = inventory.work_dir
    work_entries = scanner.scan_tree(work_root, git=False)

    comparison_roots: dict[str, str] = {}
    source_entries_raw: dict[str, dict[str, scanner.Entry]] = {}
    source_git_roots: set[str] = set()
    destination_roots: dict[str, str] = {}
    destination_entries_raw: dict[str, dict[str, scanner.Entry]] = {}
    destination_git_roots: set[str] = set()

    for source in profile.sources:
        if not source.enabled:
            continue
        if source.root:
            root = os.path.abspath(os.path.expanduser(source.root))
            if os.path.isdir(root):
                comparison_roots[source.id] = root
                source_entries_raw[source.id] = scanner.scan_tree(
                    root, git=_is_git_root(root, source)
                )
                if _is_git_root(root, source):
                    source_git_roots.add(source.id)
        if source.is_destination and source.sync_destination:
            root = os.path.abspath(os.path.expanduser(source.sync_destination))
            if os.path.isdir(root):
                destination_roots[source.id] = root
                destination_entries_raw[source.id] = scanner.scan_tree(
                    root, git=_is_git_root(root, source)
                )
                if _is_git_root(root, source):
                    destination_git_roots.add(source.id)

    baseline_reference_paths = {
        source.id: (
            source.baseline.reference_paths if source.baseline is not None else frozenset()
        )
        for source in profile.sources
    }
    (
        baseline_relevant_count,
        baseline_matches_by_path,
        baseline_content_index,
    ) = _baseline_index(profile)

    physical_by_path = {entry.path: entry for entry in inventory.included}
    excluded_physical_by_path = {entry.path: entry for entry in inventory.excluded}
    all_paths = set(work_entries) | set(physical_by_path)
    for entries in source_entries_raw.values():
        all_paths.update(entries)
    for entries in destination_entries_raw.values():
        all_paths.update(entries)
    excluded_paths = set(excluded_physical_by_path)
    if profile.exclusions:
        excluded_paths.update(
            path
            for path in all_paths
            if path not in excluded_paths
            and any(_excluded(path, pattern) for pattern in profile.exclusions)
        )

    profile_entries: dict[str, ProfileEntry] = {}
    excluded_entries: dict[str, ProfileEntry] = {}
    by_source: dict[str, list[ProfileEntry]] = {source.id: [] for source in profile.sources}
    indeterminate: list[ProfileEntry] = []
    operation_rows: list[Row] = []
    source_rows: dict[str, list[Row]] = {source.id: [] for source in profile.sources}

    for path in sorted(all_paths, key=lambda value: (value.casefold(), value)):
        dev_entry = work_entries.get(path)
        work_physical = physical_by_path.get(path)
        if work_physical is None:
            work_physical = excluded_physical_by_path.get(path)
        physical = work_physical
        if physical is None:
            physical = WorkspaceEntry(path, "file", 0, 0)
        present_in_work = (
            (dev_entry is not None and dev_entry.exists)
            or work_physical is not None
        )
        if present_in_work:
            current_kind, current_sha256, current_link_target = _current_content(
                dev_entry, work_physical
            )
            baseline_matches = _baseline_matches_for_path(
                path,
                baseline_matches_by_path.get(path, []),
                current_kind,
                current_sha256,
                current_link_target,
            )
            baseline_status = (
                _aggregate_baseline_status(baseline_matches)
                if baseline_relevant_count > 0
                else None
            )
            content_matches_elsewhere = _content_matches_elsewhere(
                path,
                current_kind,
                current_sha256,
                current_link_target,
                baseline_content_index,
            )
        else:
            baseline_matches = ()
            baseline_status = None
            content_matches_elsewhere = ()
        post_baseline_new = (
            dev_entry is not None
            and dev_entry.exists
            and baseline_relevant_count > 0
            and baseline_status == BaselineStatus.NEW
        )
        membership = _recognition_for_path(
            path,
            profile,
            source_entries_raw,
            baseline_reference_paths,
        )
        comparisons: dict[str, str] = {}
        destination_comparisons: dict[str, str] = {}
        reference_git_states: dict[str, str] = {}
        destination_git_states: dict[str, str] = {}

        for source_id, entries in source_entries_raw.items():
            if source_id not in membership.source_ids:
                continue
            ref_entry = entries.get(path)
            state = compare_pair(dev_entry, ref_entry)
            if state is not None:
                comparisons[source_id] = state
            reference_git_states[source_id] = _git_state(
                ref_entry,
                source_id in source_git_roots,
                comparison_roots[source_id],
                path,
            )

        for destination_id, entries in destination_entries_raw.items():
            if destination_id not in membership.destination_source_ids:
                continue
            target_entry = entries.get(path)
            state = compare_pair(dev_entry, target_entry)
            if state is not None:
                destination_comparisons[destination_id] = state
            destination_git_states[destination_id] = _git_state(
                target_entry,
                destination_id in destination_git_roots,
                destination_roots[destination_id],
                path,
            )

        item = ProfileEntry(
            physical=physical,
            membership=membership,
            comparisons=comparisons,
            destination_git_states=destination_git_states,
            work_dir=work_root,
            destination_comparisons=destination_comparisons,
            reference_git_states=reference_git_states,
            post_baseline_new=post_baseline_new,
            baseline_status=baseline_status,
            baseline_matches=baseline_matches,
            content_matches_elsewhere=content_matches_elsewhere,
        )
        if path in excluded_paths:
            excluded_entries[path] = item
            continue
        if path in physical_by_path:
            profile_entries[path] = item
        for source_id in set(membership.source_ids) | set(
            membership.destination_source_ids
        ):
            by_source.setdefault(source_id, []).append(item)

        if (
            path in physical_by_path
            and membership.state
            in (MembershipState.UNKNOWN, MembershipState.AMBIGUOUS)
            and not item.is_unassigned_new
        ):
            indeterminate.append(item)

        decisions = item.copy_decisions
        eligible_ids = tuple(
            decision.destination_id for decision in decisions if decision.eligible
        )
        decisions_by_key = {decision.selection_key: decision for decision in decisions}
        for decision in decisions:
            if not decision.eligible:
                continue
            target_id = decision.destination_id
            target = next((candidate for candidate in profile.sources if candidate.id == target_id), None)
            if target is not None:
                target_entry = destination_entries_raw.get(target_id, {}).get(path)
                operation_rows.append(
                    _entry_row(
                        item,
                        target,
                        destination_comparisons.get(target_id, "n/a"),
                        destination_git_states.get(target_id, "n/a"),
                        target_entry,
                        dev_entry,
                        decision.selection_key,
                        decision.blockers,
                        decision.status,
                    )
                )

        if physical.kind == "directory":
            continue
        represented = set(membership.source_ids) | set(
            membership.destination_source_ids
        )
        for source_id in sorted(represented):
            source = next((candidate for candidate in profile.sources if candidate.id == source_id), None)
            if source is None or not source.enabled:
                continue
            if source_id in membership.source_ids:
                comparison = comparisons.get(source_id)
                ref_entry = source_entries_raw.get(source_id, {}).get(path)
                git_state = reference_git_states.get(source_id, "n/a")
            else:
                comparison = destination_comparisons.get(source_id)
                ref_entry = destination_entries_raw.get(source_id, {}).get(path)
                git_state = destination_git_states.get(source_id, "n/a")
            selection_key = selection_key_for_candidates(
                path,
                source_id,
                eligible_ids,
            )
            decision = decisions_by_key.get(selection_key)
            copy_blockers = (
                decision.blockers if decision is not None else item.copy_blockers
            )
            copy_status = (
                decision.status if decision is not None else item.copy_status
            )
            source_rows.setdefault(source_id, []).append(
                _entry_row(
                    item,
                    source,
                    comparison or "n/a",
                    git_state,
                    ref_entry,
                    dev_entry,
                    selection_key,
                    copy_blockers,
                    copy_status,
                )
            )

    return ProfileAnalysis(
        profile_id=profile.id,
        work_dir=work_root,
        inventory=inventory,
        entries=tuple(profile_entries[path] for path in sorted(profile_entries)),
        source_entries={key: tuple(value) for key, value in by_source.items()},
        indeterminate=tuple(indeterminate),
        snapshot={
            "dev": {path: entry.sha256 for path, entry in work_entries.items()},
            "repos": {
                source_id: {
                    path: entry.sha256 for path, entry in destination_entries_raw.get(source_id, {}).items()
                }
                for source_id in destination_roots
            },
        },
        destination_roots=destination_roots,
        sources=tuple(profile.sources),
        rows_by_source={key: tuple(value) for key, value in source_rows.items()},
        comparison_roots=comparison_roots,
        operation_rows=tuple(operation_rows),
        unassigned_new=tuple(
            sorted(
                (
                    entry
                    for entry in profile_entries.values()
                    if entry.is_unassigned_new
                ),
                key=lambda entry: (entry.path.casefold(), entry.path),
            )
        ),
        excluded_entries=tuple(
            excluded_entries[path] for path in sorted(excluded_entries)
        ),
    )


def _excluded(path: str, pattern: str) -> bool:
    from .ignore import is_excluded

    return is_excluded(path, [pattern])
