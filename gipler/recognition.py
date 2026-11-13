"""Provider contract and resolution of workspace membership claims."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .profile import Source


class MembershipState(StrEnum):
    RECOGNIZED = "recognized"
    SHARED = "shared"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RecognitionClaim:
    source_id: str
    exclusive: bool = False
    conflict: str = ""


@dataclass(frozen=True)
class RecognitionResult:
    state: MembershipState
    source_ids: tuple[str, ...] = ()
    destination_source_ids: tuple[str, ...] = ()
    destination_source_id: str | None = None
    reasons: tuple[str, ...] = ()


class RecognitionProvider(Protocol):
    """A provider reports claims; it never chooses a destination itself."""

    kind: str

    def claims(self, relative_path: str, source: Source) -> tuple[RecognitionClaim, ...]:
        ...


class ReferenceDirectoryProvider:
    """Recognizes a relative path when its counterpart exists under source.root."""

    kind = "reference_directory"

    def claims(self, relative_path: str, source: Source) -> tuple[RecognitionClaim, ...]:
        if not source.root.strip():
            return ()
        root = os.path.abspath(os.path.expanduser(source.root))
        target = os.path.abspath(os.path.join(root, *relative_path.split("/")))
        if not _is_within(root, target):
            return ()
        return (RecognitionClaim(source.id),) if os.path.lexists(target) else ()


class RulesProvider:
    """Recognizes paths matching configured POSIX glob patterns."""

    kind = "rules"

    def claims(self, relative_path: str, source: Source) -> tuple[RecognitionClaim, ...]:
        patterns = source.config.get("patterns", ())
        if isinstance(patterns, str):
            patterns = (patterns,)
        if not isinstance(patterns, (list, tuple)):
            return ()
        if not any(_matches_rule(relative_path, str(pattern)) for pattern in patterns):
            return ()
        conflict = source.config.get("conflict", "")
        return (
            RecognitionClaim(
                source.id,
                exclusive=bool(source.config.get("exclusive", False)),
                conflict=str(conflict),
            ),
        )


_PROVIDERS: dict[str, RecognitionProvider] = {
    ReferenceDirectoryProvider.kind: ReferenceDirectoryProvider(),
    RulesProvider.kind: RulesProvider(),
}


def register_provider(provider: RecognitionProvider) -> None:
    """Register or replace an implementation for a source kind."""
    if not provider.kind:
        raise ValueError("provider kind cannot be empty")
    _PROVIDERS[provider.kind] = provider


def provider_for(source: Source) -> RecognitionProvider | None:
    return _PROVIDERS.get(source.kind)


def collect_claims(relative_path: str, sources: list[Source]) -> tuple[RecognitionClaim, ...]:
    """Collect enabled recognizer claims, de-duplicated by persistent source ID."""
    path = relative_path.replace(os.sep, "/").strip("/")
    if not path or any(part in (".", "..") for part in path.split("/")):
        return ()
    claims: dict[str, RecognitionClaim] = {}
    for source in sources:
        if not source.enabled or not source.acts_as_recognizer:
            continue
        provider = provider_for(source)
        if provider is None:
            continue
        for claim in provider.claims(path, source):
            claims[claim.source_id] = claim
    return tuple(claims[source_id] for source_id in sorted(claims))


def resolve_claims(
    claims: tuple[RecognitionClaim, ...] | list[RecognitionClaim],
    sources: list[Source],
) -> RecognitionResult:
    """Resolve membership separately from copy destination eligibility."""
    by_id = {source.id: source for source in sources}
    valid = {claim.source_id: claim for claim in claims if claim.source_id in by_id}
    source_ids = tuple(sorted(valid))
    if not source_ids:
        return RecognitionResult(MembershipState.UNKNOWN)

    reasons = tuple(sorted({claim.conflict for claim in valid.values() if claim.conflict}))
    destination_ids: set[str] = set()
    invalid_mappings: list[str] = []
    for source_id in source_ids:
        source = by_id[source_id]
        selected_targets = []
        if source.is_destination and source.sync_destination:
            selected_targets.append(source.id)
        if source.destination_source_id:
            target = by_id.get(source.destination_source_id)
            if target is None or not target.acts_as_destination:
                invalid_mappings.append(f"invalid_destination_mapping:{source.id}")
            elif target.is_destination and target.sync_destination:
                selected_targets.append(target.id)
        selected_targets = list(dict.fromkeys(selected_targets))
        if len(selected_targets) > 1:
            invalid_mappings.append(f"conflicting_destination_mapping:{source.id}")
        destination_ids.update(selected_targets)
    destinations = tuple(sorted(destination_ids))
    reasons = tuple(sorted(set(reasons) | set(invalid_mappings)))
    if reasons or (len(source_ids) > 1 and any(c.exclusive for c in valid.values())):
        return RecognitionResult(
            MembershipState.AMBIGUOUS,
            source_ids,
            destinations,
            None,
            reasons or ("exclusive_membership_conflict",),
        )

    state = MembershipState.RECOGNIZED if len(source_ids) == 1 else MembershipState.SHARED
    destination_id = destinations[0] if len(destinations) == 1 else None
    return RecognitionResult(state, source_ids, destinations, destination_id)


def recognize_path(relative_path: str, sources: list[Source]) -> RecognitionResult:
    return resolve_claims(collect_claims(relative_path, sources), sources)


def _is_within(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False


def _matches_rule(relative_path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        directory = pattern.rstrip("/")
        return relative_path == directory or relative_path.startswith(directory + "/")
    return fnmatch.fnmatchcase(relative_path, pattern)
