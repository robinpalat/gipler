"""Presentación jerárquica para las páginas de revisión del perfil."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from gipler.recognition import MembershipState


@dataclass
class HierarchyNode:
    path: str
    label: str
    icon: str = ""
    entry: object | None = None
    tooltip: str = ""
    is_dir: bool = False
    default_expanded: bool = False
    is_section: bool = False
    is_unassigned: bool = False
    restorable: bool = False
    children: list["HierarchyNode"] = field(default_factory=list)


@dataclass
class _RawNode:
    path: str
    name: str
    excluded_entry: object | None = None
    included_entry: object | None = None
    entry: object | None = None
    children: dict[str, "_RawNode"] = field(default_factory=dict)


_STATE_TEXT = {
    MembershipState.RECOGNIZED: "Reconocido",
    MembershipState.SHARED: "Compartido (pertenencia múltiple válida)",
    MembershipState.AMBIGUOUS: "Ambiguo o contradictorio",
    MembershipState.UNKNOWN: "Sin reconocimiento",
}

_STATE_COUNT = {
    MembershipState.UNKNOWN: ("sin reconocimiento", "sin reconocimiento"),
    MembershipState.AMBIGUOUS: ("ambiguo", "ambiguos"),
    MembershipState.SHARED: ("compartido", "compartidos"),
}


def _parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _name(path: str) -> str:
    parts = _parts(path)
    return parts[-1] if parts else path


def _quantity(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _ensure_path(
    roots: dict[str, _RawNode],
    path: str,
    excluded_by_path: dict[str, object] | None = None,
    included_by_path: dict[str, object] | None = None,
    entries_by_path: dict[str, object] | None = None,
) -> _RawNode:
    children = roots
    node = None
    accumulated: list[str] = []
    for part in _parts(path):
        accumulated.append(part)
        key = "/".join(accumulated)
        node = children.get(part)
        if node is None:
            node = _RawNode(path=key, name=part)
            children[part] = node
        children = node.children
        if excluded_by_path is not None and key in excluded_by_path:
            node.excluded_entry = excluded_by_path[key]
        if included_by_path is not None and key in included_by_path:
            node.included_entry = included_by_path[key]
        if entries_by_path is not None and key in entries_by_path:
            node.entry = entries_by_path[key]
    if node is None:
        raise ValueError(f"ruta vacía: {path!r}")
    return node


def _prefix_leaf_counts(entries) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.kind == "directory":
            continue
        parts = _parts(entry.path)
        for index in range(1, len(parts)):
            key = "/".join(parts[:index])
            counts[key] = counts.get(key, 0) + 1
    return counts


def _prefix_rule_counts(entries) -> dict[str, set[str]]:
    counts: dict[str, set[str]] = {}
    for entry in entries:
        rule = getattr(entry, "exclusion_rule", "")
        if not rule:
            continue
        parts = _parts(entry.path)
        limit = len(parts) if entry.kind == "directory" else len(parts) - 1
        for index in range(1, limit + 1):
            key = "/".join(parts[:index])
            counts.setdefault(key, set()).add(rule)
    return counts


def _sort_children(nodes: list[HierarchyNode]) -> list[HierarchyNode]:
    return sorted(
        nodes,
        key=lambda node: (not node.is_dir, node.path.casefold(), node.path),
    )


def _excluded_tooltip(
    node,
    rule: str,
    inherited: bool,
    rules: set[str],
    excluded_count: int,
    included_count: int,
) -> str:
    lines = [node.path]
    if node.excluded_entry is not None or node.included_entry is not None:
        physical = node.excluded_entry or node.included_entry
        lines.append(f"Tipo: {physical.kind}")
    if rule:
        lines.append(
            f"Exclusión {'heredada' if inherited else 'directa'}: {rule}"
        )
    if len(rules) > 1:
        lines.append("Reglas en el contenido: " + ", ".join(sorted(rules)))
    if node.children:
        lines.append(
            "Contenido: "
            f"{_quantity(excluded_count, 'elemento excluido', 'elementos excluidos')} · "
            f"{_quantity(included_count, 'elemento no excluido', 'elementos no excluidos')}"
        )
    return "\n".join(lines)


def _convert_excluded(
    raw: _RawNode,
    excluded_leaf_counts: dict[str, int],
    included_leaf_counts: dict[str, int],
    rules_by_dir: dict[str, set[str]],
) -> HierarchyNode | None:
    entry = raw.excluded_entry
    included_entry = raw.included_entry
    physical = entry or included_entry
    is_dir = (
        physical.kind == "directory"
        if physical is not None
        else bool(raw.children)
    )
    rule = getattr(entry, "exclusion_rule", "") if entry is not None else ""
    inherited = bool(
        entry is not None and getattr(entry, "exclusion_inherited", False)
    )

    if not is_dir:
        if entry is None:
            return None
        name = _name(raw.path) + ("  →" if entry.kind == "symlink" else "")
        nature = "heredada" if inherited else "directa"
        label = (
            f"{name}  —  Exclusión {nature}: {rule}"
            if rule
            else name
        )
        tooltip = _excluded_tooltip(
            raw, rule, inherited, set(), 0, 0
        )
        return HierarchyNode(
            path=raw.path,
            label=label,
            icon="file",
            entry=entry,
            tooltip=tooltip,
            is_dir=False,
            restorable=bool(rule),
        )

    excluded_count = excluded_leaf_counts.get(raw.path, 0)
    included_count = included_leaf_counts.get(raw.path, 0)
    rules = rules_by_dir.get(raw.path, set())
    children = [
        converted
        for child in raw.children.values()
        if (converted := _convert_excluded(
            child, excluded_leaf_counts, included_leaf_counts, rules_by_dir
        )) is not None
    ]
    if entry is not None and rule:
        status = "inherited" if inherited else "explicit"
    elif excluded_count and included_count:
        status = "mixed"
    elif excluded_count:
        status = "grouped"
    else:
        return None

    if status == "explicit":
        detail = f"Excluida · regla {rule}"
        if excluded_count:
            detail += f" · {_quantity(excluded_count, 'archivo', 'archivos')}"
    elif status == "inherited":
        detail = f"Heredada · regla {rule}"
        if excluded_count:
            detail += f" · {_quantity(excluded_count, 'archivo', 'archivos')}"
    elif status == "mixed":
        detail = (
            f"Parcial · {_quantity(excluded_count, 'excluido', 'excluidos')} · "
            f"{_quantity(included_count, 'no excluido', 'no excluidos')}"
        )
    else:
        detail = (
            "Solo contenido excluido · "
            f"{_quantity(excluded_count, 'archivo', 'archivos')}"
        )

    return HierarchyNode(
        path=raw.path,
        label=f"{raw.name}/  —  {detail}",
        icon="folder",
        entry=physical,
        tooltip=_excluded_tooltip(
            raw, rule, inherited, rules, excluded_count, included_count
        ),
        is_dir=True,
        default_expanded=status == "mixed",
        restorable=bool(entry is not None and rule),
        children=_sort_children(children),
    )


def build_excluded_tree(excluded, included) -> list[HierarchyNode]:
    excluded_by_path = {entry.path: entry for entry in excluded}
    included_by_path = {entry.path: entry for entry in included}
    roots: dict[str, _RawNode] = {}
    for path in excluded_by_path:
        _ensure_path(roots, path, excluded_by_path, included_by_path)

    excluded_leaf_counts = _prefix_leaf_counts(excluded_by_path.values())
    included_leaf_counts = _prefix_leaf_counts(included_by_path.values())
    rules_by_dir = _prefix_rule_counts(excluded_by_path.values())
    nodes = [
        converted
        for raw in roots.values()
        if (converted := _convert_excluded(
            raw, excluded_leaf_counts, included_leaf_counts, rules_by_dir
        )) is not None
    ]
    return _sort_children(nodes)


def _membership_tooltip(
    raw: _RawNode,
    entry,
    counts: Counter,
    resolved: int,
    unassigned: bool,
) -> str:
    lines = [raw.path]
    physical = entry
    if physical is not None:
        lines.append(f"Tipo: {physical.kind}")
        if unassigned:
            lines.append("Archivo nuevo aparecido tras la línea de base; sin referencia asignada")
        else:
            state = physical.membership.state
            lines.append(f"Pertenencia: {_STATE_TEXT.get(state, state.value)}")
            references = ", ".join(physical.membership.source_ids) or "ninguna"
            lines.append(f"Referencias: {references}")
            if physical.membership.reasons:
                lines.append("Motivos: " + ", ".join(physical.membership.reasons))
    if counts:
        summary = []
        for state in (MembershipState.UNKNOWN, MembershipState.AMBIGUOUS, MembershipState.SHARED):
            if counts.get(state):
                singular, plural = _STATE_COUNT[state]
                if unassigned and state is MembershipState.UNKNOWN:
                    singular = plural = "sin asignar"
                summary.append(
                    f"{counts[state]} {singular if counts[state] == 1 else plural}"
                )
        lines.append("Contenido: " + " · ".join(summary))
    if resolved:
        lines.append(
            f"Contenido resuelto: {_quantity(resolved, 'archivo', 'archivos')}"
        )
    return "\n".join(lines)


def _convert_membership(
    raw: _RawNode,
    all_by_path: dict[str, object],
    counts_by_dir: dict[str, Counter],
    resolved_by_dir: dict[str, int],
    unassigned: bool,
) -> HierarchyNode:
    entry = raw.entry
    physical = entry or all_by_path.get(raw.path)
    is_dir = (
        physical.kind == "directory"
        if physical is not None
        else bool(raw.children)
    )
    children = [
        _convert_membership(
            child, all_by_path, counts_by_dir, resolved_by_dir, unassigned
        )
        for child in raw.children.values()
    ]

    if not is_dir:
        state = entry.membership.state
        state_text = "Nuevo sin asignar" if unassigned else _STATE_TEXT.get(state, state.value)
        name = raw.name + ("  →" if entry.kind == "symlink" else "")
        return HierarchyNode(
            path=raw.path,
            label=f"{name}  [{state_text}]",
            icon="file",
            entry=entry,
            tooltip=_membership_tooltip(raw, entry, Counter(), 0, unassigned),
            is_dir=False,
            is_unassigned=unassigned,
        )

    aggregate = counts_by_dir.get(raw.path, Counter())
    own_state = entry.membership.state if entry is not None else None
    descendant = Counter(aggregate)
    if own_state is not None:
        descendant[own_state] -= 1
        if descendant[own_state] <= 0:
            del descendant[own_state]
    resolved = resolved_by_dir.get(raw.path, 0)

    details = []
    for state in (MembershipState.UNKNOWN, MembershipState.AMBIGUOUS, MembershipState.SHARED):
        count = descendant.get(state, 0)
        if count:
            singular, plural = _STATE_COUNT[state]
            if unassigned and state is MembershipState.UNKNOWN:
                singular = plural = "sin asignar"
            details.append(
                f"{count} {singular if count == 1 else plural}"
            )
    if resolved:
        details.append(
            _quantity(resolved, "resuelto", "resueltos")
        )

    label = f"{raw.name}/"
    if own_state is not None:
        own_text = "Nuevo sin asignar" if unassigned else _STATE_TEXT.get(own_state, own_state.value)
        label += f"  [{own_text}]"
    if details:
        label += "  —  " + " · ".join(details)

    return HierarchyNode(
        path=raw.path,
        label=label,
        icon="folder",
        entry=entry,
        tooltip=_membership_tooltip(
            raw, entry, descendant, resolved, unassigned
        ),
        is_dir=True,
        default_expanded=True,
        is_unassigned=unassigned,
        children=_sort_children(children),
    )


def _build_membership_tree(
    entries_by_path: dict[str, object],
    all_by_path: dict[str, object],
    unassigned: bool,
) -> list[HierarchyNode]:
    roots: dict[str, _RawNode] = {}
    for path in entries_by_path:
        _ensure_path(roots, path, entries_by_path=entries_by_path)

    counts_by_dir: dict[str, Counter] = {}
    for entry in entries_by_path.values():
        parts = _parts(entry.path)
        for index in range(1, len(parts) + 1):
            key = "/".join(parts[:index])
            counts_by_dir.setdefault(key, Counter())[entry.membership.state] += 1

    resolved_by_dir: dict[str, int] = {}
    for entry in all_by_path.values():
        if (
            entry.kind == "directory"
            or entry.membership.state is not MembershipState.RECOGNIZED
        ):
            continue
        parts = _parts(entry.path)
        for index in range(1, len(parts)):
            key = "/".join(parts[:index])
            resolved_by_dir[key] = resolved_by_dir.get(key, 0) + 1

    nodes = [
        _convert_membership(
            raw, all_by_path, counts_by_dir, resolved_by_dir, unassigned
        )
        for raw in roots.values()
    ]
    return _sort_children(nodes)


def build_indeterminate_sections(review_entries, unassigned, all_entries) -> list[HierarchyNode]:
    review_by_path = {entry.path: entry for entry in review_entries}
    unassigned_by_path = {entry.path: entry for entry in unassigned}
    for path in unassigned_by_path:
        review_by_path.pop(path, None)
    all_by_path = {entry.path: entry for entry in all_entries}
    all_by_path.update(unassigned_by_path)
    all_by_path.update(review_by_path)

    sections: list[HierarchyNode] = []
    if unassigned_by_path:
        sections.append(
            HierarchyNode(
                path="",
                label="Archivos nuevos",
                is_section=True,
                default_expanded=True,
                is_unassigned=True,
                children=_build_membership_tree(
                    unassigned_by_path, all_by_path, True
                ),
            )
        )
    if review_by_path:
        review_nodes = _build_membership_tree(
            review_by_path, all_by_path, False
        )
        if unassigned_by_path:
            sections.append(
                HierarchyNode(
                    path="",
                    label="Otros indeterminados",
                    is_section=True,
                    default_expanded=True,
                    children=review_nodes,
                )
            )
        else:
            sections.extend(review_nodes)
    return sections
