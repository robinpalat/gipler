"""Política única de elegibilidad estructural para la copia.

Análisis, GUI, TUI, preparación y motor comparten estas decisiones. El
motor conserva además sus revalidaciones físicas y de concurrencia.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .recognition import MembershipState
from .selection import SelectionKey, make_selection_key

COPYABLE_AXIS_A = frozenset({"new_in_dev", "modified_in_dev"})
COPYABLE_COMPARISONS = COPYABLE_AXIS_A
BLOCKING_INCIDENCES = frozenset(
    {
        "shared_file",
        "status_unrecognized",
        "status_development",
        "unknown_owner",
        "ambiguous",
        "external_dependency",
        "path_outside_prefix",
        "symlink_escapes_allowed_dirs",
        "excluded",
    }
)

STATUS_COPIABLE = "copiable"
STATUS_BLOCKED = "bloqueada"
STATUS_NO_APPLICABLE = "no_aplica"
STATUS_REQUIRES_ASSIGNMENT = "requiere_asignacion"

_MESSAGES = {
    "shared_file": "Archivo compartido: asigne una referencia antes de copiar",
    "ambiguous": "Pertenencia ambigua o contradictoria",
    "sin_pertenencia": "Sin referencia asignada",
    "sin_destino_mapeado": "La referencia no tiene destino de copia",
    "destino_no_configurado": "Destino no configurado o inexistente",
    "sin_cambios": "Sin cambios: no hay nada que copiar",
    "missing_in_dev": "El archivo no existe en el árbol de trabajo",
    "missing_in_reference": "El archivo no existe en la referencia",
    "origen_no_existe_en_analisis": "El origen no existía en el análisis",
    "sin_destino_o_propiedad": "Sin destino o propietario conocido",
    "ruta_fuera_del_repo": "La ruta quedaría fuera del destino",
    "destino_con_modificacion_local": "El destino tiene cambios locales",
    "destino_ignorado": "El destino está ignorado por Git",
    "destino_untracked_no_sobrescribir": "El destino es untracked y se sobrescribiría contenido local",
    "symlink_escapes_allowed_dirs": "El symlink apunta fuera del árbol permitido",
    "presente_en_ambos_repos: resolucion_manual": "Presente en ambos repositorios: resolución manual",
    "es_directorio": "Los directorios no se copian como archivo",
    "origen_ya_no_existe": "El origen ya no existe",
    "origen_cambio_desde_analisis": "El origen cambió desde el análisis",
    "symlink_externo_rechazado": "El symlink de origen apunta fuera del árbol permitido",
    "destino_cambio_desde_analisis": "El destino cambió desde el análisis",
    "destino_desaparecio": "El destino desapareció desde el análisis",
}


@dataclass(frozen=True)
class CopyDecision:
    destination_id: str
    path: str
    status: str
    blockers: tuple[str, ...] = ()

    @property
    def selection_key(self) -> SelectionKey | None:
        return make_selection_key(self.destination_id, self.path)

    @property
    def eligible(self) -> bool:
        return self.status == STATUS_COPIABLE


def describe_blocker(code: str) -> str:
    if code in _MESSAGES:
        return _MESSAGES[code]
    if code.startswith("incidencias_bloqueantes:"):
        names = code.partition(":")[2]
        return "Incidencias bloqueantes: " + ", ".join(
            _MESSAGES.get(name, name) for name in names.split(",") if name
        )
    if code.startswith("pertenencia_con_incidencias:"):
        names = code.partition(":")[2]
        return "Pertenencia con incidencias: " + ", ".join(
            _MESSAGES.get(name, name) for name in names.split(",") if name
        )
    if code.startswith("eje_a_no_copiable:"):
        return "Estado de origen no copiable: " + code.partition(":")[2]
    if code.startswith("comparacion_no_copiable:"):
        return "Comparación no copiable: " + code.partition(":")[2]
    return code


def describe_blockers(codes) -> list[str]:
    return [describe_blocker(str(code)) for code in codes]


def destination_git_blockers(git_state: str, comparison: str) -> tuple[str, ...]:
    if git_state == "tracked_modified":
        return ("destino_con_modificacion_local",)
    if git_state == "ignored":
        return ("destino_ignorado",)
    if git_state == "untracked" and comparison == "modified_in_dev":
        return ("destino_untracked_no_sobrescribir",)
    return ()


def _symlink_escapes(entry) -> bool:
    physical = entry.physical
    if physical.kind != "symlink":
        return False
    work_root = os.path.realpath(entry.work_dir)
    resolved = os.path.realpath(
        os.path.join(work_root, os.path.dirname(entry.path), physical.link_target)
    )
    try:
        return os.path.commonpath((work_root, resolved)) != work_root
    except ValueError:
        return True


def membership_blockers(entry) -> tuple[str, ...]:
    state = entry.membership.state
    if state == MembershipState.SHARED:
        return ("shared_file",)
    if state == MembershipState.AMBIGUOUS:
        return ("ambiguous",)
    if state != MembershipState.RECOGNIZED:
        return ("sin_pertenencia",)
    if entry.membership.reasons:
        return (
            "pertenencia_con_incidencias:"
            + ",".join(sorted(set(entry.membership.reasons))),
        )
    return ()


def entry_copy_decision(entry, destination_id: str) -> CopyDecision:
    blockers = list(membership_blockers(entry))
    if entry.physical.kind == "directory":
        blockers.append("es_directorio")
    if entry.membership.state == MembershipState.SHARED:
        return CopyDecision(
            destination_id,
            entry.path,
            STATUS_REQUIRES_ASSIGNMENT,
            tuple(dict.fromkeys(blockers or ("shared_file",))),
        )
    if entry.membership.state != MembershipState.RECOGNIZED:
        return CopyDecision(
            destination_id,
            entry.path,
            STATUS_BLOCKED,
            tuple(dict.fromkeys(blockers)),
        )
    if destination_id not in entry.membership.destination_source_ids:
        blockers.append("sin_destino_mapeado")
    comparison = entry.destination_comparisons.get(destination_id)
    git_state = entry.destination_git_states.get(destination_id, "n/a")
    if comparison is None:
        blockers.append("destino_no_configurado")
    elif comparison == "identical":
        blockers.append("sin_cambios")
    elif comparison == "missing_in_dev":
        blockers.append("missing_in_dev")
    elif comparison not in COPYABLE_COMPARISONS:
        blockers.append(f"comparacion_no_copiable:{comparison}")
    else:
        blockers.extend(destination_git_blockers(git_state, comparison))
        if _symlink_escapes(entry):
            blockers.append("symlink_escapes_allowed_dirs")
    blockers = list(dict.fromkeys(blockers))
    if blockers:
        status = (
            STATUS_NO_APPLICABLE
            if blockers == ["sin_cambios"]
            else STATUS_BLOCKED
        )
        return CopyDecision(destination_id, entry.path, status, tuple(blockers))
    return CopyDecision(destination_id, entry.path, STATUS_COPIABLE)


def entry_copy_decisions(entry) -> tuple[CopyDecision, ...]:
    if entry.physical.kind == "directory":
        return ()
    if entry.membership.state not in (
        MembershipState.RECOGNIZED,
        MembershipState.SHARED,
    ):
        return ()
    return tuple(
        entry_copy_decision(entry, destination_id)
        for destination_id in sorted(set(entry.membership.destination_source_ids))
    )


def entry_copy_blockers(entry) -> tuple[str, ...]:
    blockers = list(membership_blockers(entry))
    if entry.physical.kind == "directory":
        blockers.append("es_directorio")
    if (
        entry.membership.state == MembershipState.RECOGNIZED
        and not entry.membership.destination_source_ids
    ):
        blockers.append("sin_destino_mapeado")
    for decision in entry_copy_decisions(entry):
        if decision.status == STATUS_NO_APPLICABLE:
            continue
        blockers.extend(decision.blockers)
    return tuple(dict.fromkeys(blockers))


def entry_copy_status(entry) -> str:
    if entry.physical.kind == "directory":
        return STATUS_BLOCKED
    if entry.membership.state == MembershipState.SHARED:
        return STATUS_REQUIRES_ASSIGNMENT
    decisions = entry_copy_decisions(entry)
    if any(decision.status == STATUS_COPIABLE for decision in decisions):
        return STATUS_COPIABLE
    if any(decision.status == STATUS_REQUIRES_ASSIGNMENT for decision in decisions):
        return STATUS_REQUIRES_ASSIGNMENT
    if any(decision.status == STATUS_BLOCKED for decision in decisions):
        return STATUS_BLOCKED
    blockers = entry_copy_blockers(entry)
    if blockers and blockers != ("sin_cambios",):
        return STATUS_BLOCKED
    return STATUS_NO_APPLICABLE


def reverse_row_blockers(row) -> tuple[str, ...]:
    blockers: list[str] = []
    if row.axis_a == "identical":
        return ("sin_cambios",)
    if row.axis_a == "new_in_dev":
        return ("missing_in_reference",)
    if row.axis_a not in ("modified_in_dev", "missing_in_dev"):
        blockers.append(f"comparacion_no_copiable:{row.axis_a}")
    if not row.owner or row.owner == "sin determinar":
        blockers.append("sin_destino_o_propiedad")
    bad = BLOCKING_INCIDENCES & set(row.incidences)
    if bad:
        blockers.append("incidencias_bloqueantes:" + ",".join(sorted(bad)))
    if "present_in_both_repos" in row.incidences or "duplicate_tracked_in_both" in row.incidences:
        blockers.append("presente_en_ambos_repos: resolucion_manual")
    return tuple(dict.fromkeys(blockers))


def static_row_blockers(row) -> tuple[str, ...]:
    blockers: list[str] = []
    if row.axis_a == "identical":
        return ("sin_cambios",)
    if row.axis_a == "missing_in_dev":
        return ("missing_in_dev",)
    if row.axis_a not in COPYABLE_AXIS_A:
        blockers.append(f"eje_a_no_copiable:{row.axis_a}")
    if not row.owner or row.owner == "sin determinar":
        blockers.append("sin_destino_o_propiedad")
    bad = BLOCKING_INCIDENCES & set(row.incidences)
    if bad:
        blockers.append("incidencias_bloqueantes:" + ",".join(sorted(bad)))
    blockers.extend(destination_git_blockers(row.axis_b, row.axis_a))
    if "present_in_both_repos" in row.incidences or "duplicate_tracked_in_both" in row.incidences:
        blockers.append("presente_en_ambos_repos: resolucion_manual")
    return tuple(dict.fromkeys(blockers))
