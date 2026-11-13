"""Profile analysis adapted to Gipler's shared scanner/comparator/report model."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import scanner
from .comparator import compare_pair
from .profile import Profile, Source
from .recognition import (
    MembershipState,
    RecognitionClaim,
    RecognitionResult,
    collect_claims,
    resolve_claims,
)
from .report import Row
from .workspace import WorkspaceEntry, WorkspaceInventory, scan_workspace


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
    def eligible_destination_source_ids(self) -> tuple[str, ...]:
        if self.membership.state not in (
            MembershipState.RECOGNIZED,
            MembershipState.SHARED,
        ) or self.physical.kind == "directory":
            return ()
        eligible: list[str] = []
        for destination_id in self.membership.destination_source_ids:
            if self.destination_comparisons.get(destination_id) not in (
                "new_in_dev",
                "modified_in_dev",
            ):
                continue
            if self.destination_git_states.get(destination_id) in (
                "tracked_modified",
                "ignored",
            ):
                continue
            if (
                self.destination_git_states.get(destination_id) == "untracked"
                and self.destination_comparisons.get(destination_id) == "modified_in_dev"
            ):
                continue
            if self.physical.kind == "symlink":
                work_root = os.path.realpath(self.work_dir)
                resolved = os.path.realpath(
                    os.path.join(
                        work_root,
                        os.path.dirname(self.path),
                        self.physical.link_target,
                    )
                )
                try:
                    if os.path.commonpath((work_root, resolved)) != work_root:
                        continue
                except ValueError:
                    continue
            eligible.append(destination_id)
        return tuple(sorted(eligible))

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


def _entry_row(
    entry: ProfileEntry,
    source: Source,
    comparison: str,
    git_state: str,
    ref_entry: scanner.Entry | None,
    dev_entry: scanner.Entry | None,
    selection_key: tuple[str, str] | None = None,
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

    baseline_work_paths = {
        source.id: (
            source.baseline.work_paths if source.baseline is not None else frozenset()
        )
        for source in profile.sources
    }
    baseline_reference_paths = {
        source.id: (
            source.baseline.reference_paths if source.baseline is not None else frozenset()
        )
        for source in profile.sources
    }
    baseline_preexisting_paths = {
        source.id: (
            source.baseline.preexisting_reference_paths
            if source.baseline is not None
            else frozenset()
        )
        for source in profile.sources
    }

    physical_by_path = {entry.path: entry for entry in inventory.included}
    all_paths = set(work_entries) | set(physical_by_path)
    for entries in source_entries_raw.values():
        all_paths.update(entries)
    for entries in destination_entries_raw.values():
        all_paths.update(entries)
    all_paths = {
        path for path in all_paths
        if not any(
            _excluded(path, pattern) for pattern in profile.exclusions
        )
    }

    profile_entries: dict[str, ProfileEntry] = {}
    by_source: dict[str, list[ProfileEntry]] = {source.id: [] for source in profile.sources}
    indeterminate: list[ProfileEntry] = []
    operation_rows: list[Row] = []
    source_rows: dict[str, list[Row]] = {source.id: [] for source in profile.sources}

    for path in sorted(all_paths, key=lambda value: (value.casefold(), value)):
        dev_entry = work_entries.get(path)
        physical = physical_by_path.get(path)
        if physical is None:
            physical = WorkspaceEntry(path, "file", 0, 0)
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
            post_baseline_new=(
                dev_entry is not None
                and dev_entry.exists
                and any(
                    source.enabled
                    and source.baseline is not None
                    and path not in baseline_work_paths[source.id]
                    and path not in baseline_preexisting_paths[source.id]
                    for source in profile.sources
                )
            ),
        )
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

        for target_id in item.eligible_destination_source_ids:
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
                        (target_id, path),
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
            eligible_ids = item.eligible_destination_source_ids
            if len(eligible_ids) == 1:
                selection_key = (eligible_ids[0], path)
            elif source_id in eligible_ids:
                selection_key = (source_id, path)
            else:
                selection_key = None
            source_rows.setdefault(source_id, []).append(
                _entry_row(
                    item,
                    source,
                    comparison or "n/a",
                    git_state,
                    ref_entry,
                    dev_entry,
                    selection_key,
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
    )


def _excluded(path: str, pattern: str) -> bool:
    from .ignore import is_excluded

    return is_excluded(path, [pattern])
