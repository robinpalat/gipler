"""Fase 2 — Classifier (spec §3, §4, §5.3).

Lee los nueve manifiestos cnfg.sh (solo la sección FILES:, solo lectura),
deriva destino por STATUS (external->addons, native->principal,
development->sin destino), aplica exclusiones de dev-sync.toml si existe,
detecta compartidos, huérfanos de manifiesto y rutas anómalas.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field

# Caso confirmado por el usuario (spec §3.2/§3.3/§7.9): propiedad de Podcasts,
# destino repo de addons. La ruta declarada "/images/img.11.png" se conserva
# y se resuelve respecto de la raíz; nunca se inventa otra ruta.
DECIDED = {
    "images/img.11.png": "Podcasts",
}

STATUS_DEST = {"external": "addons", "native": "principal"}


@dataclass
class Manifest:
    addon: str
    status: str
    fields: dict = field(default_factory=dict)
    files: list[str] = field(default_factory=list)  # normalizadas (sin / inicial)


def _parse_cnfg(path: str) -> tuple[dict, list[str]]:
    fields: dict[str, str] = {}
    files: list[str] = []
    in_files = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.startswith("#"):
                in_files = False
                continue
            body = line[1:].strip()
            if body.startswith("==="):
                in_files = False
                continue
            if "FILES:" in body and body.replace("FILES:", "").strip() in ("",):
                in_files = True
                continue
            if in_files:
                if body == "" or body.startswith("====="):
                    in_files = False
                    continue
                # Entradas con forma "#   ruta" (con o sin guion)
                entry = body.lstrip("-").strip()
                if not entry or entry.startswith("#"):
                    continue
                files.append(entry)
                continue
            m = re.match(r"(ID|NAME|VERSION|STATUS|DESCRIPTION)\s*:\s*(.*)$", body)
            if m:
                fields[m.group(1)] = m.group(2).strip()
    return fields, files


def _normalize(p: str) -> str:
    p = p.strip()
    if p.startswith("/"):
        p = p[1:]
    return p


def parse_manifests(dev: str) -> dict[str, Manifest]:
    """Lee Dev/addons/<Addon>/cnfg.sh de cada addon. Solo lectura."""
    manifests: dict[str, Manifest] = {}
    addons_dir = os.path.join(dev, "addons")
    if not os.path.isdir(addons_dir):
        return manifests
    for addon in sorted(os.listdir(addons_dir)):
        cnfg = os.path.join(addons_dir, addon, "cnfg.sh")
        if os.path.isfile(cnfg):
            fields, raw_files = _parse_cnfg(cnfg)
            manifests[addon] = Manifest(
                addon=addon,
                status=fields.get("STATUS", ""),
                fields=fields,
                files=[_normalize(p) for p in raw_files],
            )
    return manifests


@dataclass
class Classification:
    owner: str = ""        # addon | "núcleo" | "" (sin determinar)
    destination: str = ""  # principal | addons | "" (sin determinar)
    incidences: list[str] = field(default_factory=list)
    shared: bool = False
    ambiguous: bool = False
    external_dep: bool = False
    excluded: bool = False
    context: str = ""      # p. ej. carpeta addons/<Addon>/ aunque no determine propiedad

    def has(self, code: str) -> bool:
        return code in self.incidences


def load_exclusions(dev: str) -> tuple[list[str], str | None]:
    """(patterns, aviso). Si dev-sync.toml no existe: ([], 'devsync_missing')."""
    conf = os.path.join(dev, "dev-sync.toml")
    if not os.path.isfile(conf):
        return [], "devsync_missing"
    try:
        with open(conf, "rb") as f:
            data = tomllib.load(f)
        patterns = list(data.get("exclude", {}).get("patterns", []))
        return patterns, None
    except Exception:
        return [], "devsync_unparseable"


def _is_excluded(path: str, patterns: list[str]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def classify(
    dev: str,
    dev_paths: set[str],
    manifests: dict[str, Manifest],
    exclude_patterns: list[str],
    duplicate_codes: dict[str, str] | None = None,
) -> dict[str, Classification]:
    """Clasifica cada path de Dev (y las rutas declaradas ausentes)."""
    owner_of: dict[str, list[str]] = {}
    for addon, m in manifests.items():
        for p in m["files"] if isinstance(m, dict) else m.files:
            owner_of.setdefault(p, []).append(addon)

    result: dict[str, Classification] = {}

    def dest_for(addon: str) -> str:
        return STATUS_DEST.get(manifests[addon].status, "")

    all_paths = set(dev_paths) | set(owner_of)
    for path in sorted(all_paths):
        c = Classification()
        owners = owner_of.get(path, [])
        # Caso decidido images/img.11.png -> Podcasts (addons), archivo ordinario.
        if path in DECIDED:
            addon = DECIDED[path]
            c.owner = addon
            c.destination = dest_for(addon) or "addons"
            c.excluded = _is_excluded(path, exclude_patterns)
            if c.excluded:
                c.incidences.append("excluded")
            if duplicate_codes and path in duplicate_codes:
                c.incidences.append(duplicate_codes[path])
            result[path] = c
            continue
        if len(owners) > 1:
            c.owner = "|".join(sorted(owners))
            c.destination = ""
            c.shared = True
            c.ambiguous = True
            c.incidences.append("shared_file")
            result[path] = c
            continue
        if owners:
            addon = owners[0]
            c.owner = addon
            c.destination = dest_for(addon)
            if manifests[addon].status not in STATUS_DEST and manifests[addon].status:
                if manifests[addon].status == "development":
                    c.ambiguous = True
                    c.incidences.append("status_development")
                else:
                    c.ambiguous = True
                    c.incidences.append("status_unrecognized")
            if manifests[addon].status == "":
                c.ambiguous = True
                c.incidences.append("status_unrecognized")
            if not (path.startswith(f"addons/{addon}/") or path.startswith("ifs/extensions/")):
                c.external_dep = True
                c.incidences.append("external_dependency")
                c.incidences.append("path_outside_prefix")
            if path not in dev_paths:
                c.incidences.append("manifest_missing_file")
            result[path] = c
            continue
        # Sin dueño declarado.
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "addons" and parts[1] in manifests:
            c.context = f"addons/{parts[1]}/"
            c.incidences.append("manifest_undeclared_file")
            result[path] = c
            continue
        c.owner = "núcleo"
        c.destination = "principal"
        result[path] = c

    for path, c in result.items():
        if _is_excluded(path, exclude_patterns):
            c.excluded = True
            if "excluded" not in c.incidences:
                c.incidences.append("excluded")
    return result
