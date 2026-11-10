"""Motor de copia (Etapa 2 spec §7.6-7.9, solo tras autorización).

Recibe filas ya clasificadas de análisis, vuelve a verificar origen y
destino contra la huella del análisis (snapshot) y solo ejecuta lo
explícitamente autorizado. Sin transacciones, journals ni backups.
Nunca ejecuta comandos Git.

Protección TOCTOU sin os.replace():
- Los directorios padre se abren con O_DIRECTORY|O_NOFOLLOW un componente
  a la vez con dir_fd, de modo que un symlink intermedio o una sustitución
  de directorio los rechaza (fijación del directorio real).
- El destino nuevo se crea con O_CREAT|O_EXCL: si otro proceso lo creó
  tras la verificación, la apertura falla sin tocarlo.
- El destino existente se abre con O_NOFOLLOW y su contenido se hashea
  desde el FD abierto antes de escribir; si difiere de la huella, se
  bloquea sin escribir. Un symlink sustituto abre con ELOOP.
- La copia escribe a través del FD abierto (ftruncate+write) y Fchmod,
  sin renombrar sobre el destino.
"""
from __future__ import annotations

import errno
import hashlib
import os

BAD_INCIDENCES = {
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


class PathEscape(OSError):
    pass


class Op:
    def __init__(self, row, dev: str, repos: dict[str, str], status: str, blockers: list[str]):
        self.path = row.path
        self.destination = row.destination
        self.axis_a = row.axis_a
        self.axis_b = row.axis_b
        self.owner = row.owner
        self.status = status  # copiable | bloqueada | identica
        self.blockers = blockers
        self.src = os.path.join(dev, row.path)
        self.dst = os.path.join(repos[row.destination], row.path) if row.destination in repos else ""
        self.dev_root = dev
        self.repo_root = repos[row.destination] if row.destination in repos else ""
        self.src_mode = 0
        self.src_size = 0
        self.is_link = False
        self.src_hash: str | None = None
        self.snap_repo_hash: str | None = None  # None = destino ausente en el análisis

    def __repr__(self):
        return f"Op({self.path} -> {self.destination} {self.status})"


def _sha(path: str) -> str:
    if os.path.islink(path):
        return hashlib.sha256(("symlink:" + os.readlink(path)).encode()).hexdigest()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(root: str, target: str) -> bool:
    root = os.path.abspath(root)
    target = os.path.abspath(target)
    return os.path.commonpath([root]) == os.path.commonpath([root, target])


def _real_inside(root: str, target: str) -> bool:
    return _inside(os.path.realpath(root), os.path.realpath(target))


def build_operations(rows, selection: set[tuple[str, str]], dev: str,
                     repos: dict[str, str], snapshot: dict) -> list[Op]:
    """Verifica cada (destino, path) seleccionado contra la huella.
    Devuelve operaciones con motivo de bloqueo cuando corresponda."""
    ops: list[Op] = []
    by_key = {(r.destination, r.path): r for r in rows}
    for key in sorted(selection):
        r = by_key.get(key)
        if r is None:
            continue
        blockers: list[str] = []
        if r.destination not in ("principal", "addons"):
            blockers.append("sin_destino_o_propiedad")
            ops.append(Op(r, dev, repos, "bloqueada", blockers))
            continue
        if not _inside(repos[r.destination], os.path.join(repos[r.destination], r.path)):
            blockers.append("ruta_fuera_del_repo")
        # Eje A.
        if r.axis_a == "identical":
            ops.append(Op(r, dev, repos, "identica", ["sin_cambios"]))
            continue
        if r.axis_a == "missing_in_dev":
            ops.append(Op(r, dev, repos, "bloqueada", ["missing_in_dev: nunca copiar"]))
            continue
        if r.axis_a not in ("new_in_dev", "modified_in_dev"):
            blockers.append(f"eje_a_no_copiable:{r.axis_a}")
        if not r.owner or r.owner == "sin determinar":
            blockers.append("sin_destino_o_propiedad")
        if BAD_INCIDENCES & set(r.incidences):
            blockers.append("incidencias_bloqueantes:" + ",".join(sorted(BAD_INCIDENCES & set(r.incidences))))
        # Eje B.
        if r.axis_b == "tracked_modified":
            blockers.append("destino_con_modificacion_local")
        elif r.axis_b == "ignored" and (not _inside(repos[r.destination], os.path.join(repos[r.destination], r.path)) or r.axis_a == "modified_in_dev"):
            blockers.append("destino_ignorado")
        elif r.axis_b == "ignored":
            blockers.append("destino_ignorado_no_copia_automatica")
        elif r.axis_b == "untracked" and r.axis_a == "modified_in_dev":
            blockers.append("destino_untracked_no_sobrescribir")
        if "present_in_both_repos" in r.incidences or "duplicate_tracked_in_both" in r.incidences:
            blockers.append("presente_en_ambos_repos: resolucion_manual")
        # Re-check origen y destino frente a la huella del análisis.
        src = os.path.join(dev, r.path)
        dst = os.path.join(repos[r.destination], r.path) if r.destination in repos else ""
        snap_dev = (snapshot.get("dev") or {}).get(r.path)
        if not os.path.lexists(src):
            blockers.append("origen_ya_no_existe")
        elif snap_dev is not None and _sha(src) != snap_dev:
            blockers.append("origen_cambio_desde_analisis")
        if os.path.islink(src):
            resolved = os.path.normpath(os.path.join(dev, os.path.dirname(r.path), os.readlink(src)))
            if not _inside(dev, resolved) or not _real_inside(dev, resolved):
                blockers.append("symlink_externo_rechazado")
        snap_repo = (snapshot.get("repos") or {}).get(r.destination, {}).get(r.path)
        if os.path.lexists(dst):
            if snap_repo is None or _sha(dst) != snap_repo:
                blockers.append("destino_cambio_desde_analisis")
        elif snap_repo is not None:
            blockers.append("destino_desaparecio")
        src_mode = os.lstat(src).st_mode & 0o777 if os.path.lexists(src) else 0
        op = Op(r, dev, repos, "bloqueada" if blockers else "copiable", blockers)
        op.src_mode = src_mode
        op.src_size = os.lstat(src).st_size if os.path.lexists(src) else 0
        op.is_link = os.path.islink(src) if os.path.lexists(src) else False
        op.src_hash = _sha(src) if os.path.lexists(src) else None
        op.snap_repo_hash = snap_repo
        ops.append(op)
    return ops


def preview(ops: list[Op]) -> str:
    lines = ["Vista previa de operaciones (sin ejecutar):"]
    for o in ops:
        lines.append(
            f"  {o.path} -> {o.destination}: {o.status}"
            + (f" (bloqueos: {', '.join(o.blockers)})" if o.blockers else "")
        )
    if not ops:
        lines.append("  (sin operaciones seleccionadas — nada ejecutado)")
    return "\n".join(lines)


def _sha_fd(fd: int) -> str:
    h = hashlib.sha256()
    offset = 0
    while True:
        chunk = os.pread(fd, 65536, offset)
        if not chunk:
            break
        h.update(chunk)
        offset += len(chunk)
    return h.hexdigest()


def _open_parents(repo_root: str, rel: str) -> tuple[int, str, list[int]]:
    """Abre la raíz y cada directorio padre con O_NOFOLLOW.
    Devuelve (fd_parent, nombre_final, fds_para_cerrar).
    Rechaza symlinks y componentes que no sean directorios."""
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PathEscape("ruta escapes rechazada: " + rel)
    fds: list[int] = []
    try:
        current = os.open(repo_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        for f in fds:
            os.close(f)
        raise PathEscape(f"raíz no directorio: {e}") from e
    fds.append(current)
    for part in parts[:-1]:
        try:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
        except FileNotFoundError:
            try:
                os.mkdir(part, dir_fd=current)
            except FileExistsError:
                for f in fds:
                    os.close(f)
                raise PathEscape(f"padre no directorio o symlink: {part}") from None
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
        except OSError as e:
            for f in fds:
                os.close(f)
            raise PathEscape(f"padre no es directorio real: {part} ({e})") from e
        fds.append(nxt)
        current = nxt
    return current, parts[-1], fds


def execute_operations(ops: list[Op], authorized: bool) -> list[dict]:
    """Ejecuta SOLO las ops copiables cuando authorized=True.
    Sin os.replace(): protege contra modificación concurrente del destino."""
    results: list[dict] = []
    for o in ops:
        if o.status == "identica":
            results.append({"path": o.path, "status": "omitida_identica"})
            continue
        if o.status != "copiable":
            results.append({"path": o.path, "status": "bloqueada", "detail": "; ".join(o.blockers)})
            continue
        if not authorized:
            results.append({"path": o.path, "status": "cancelada"})
            continue
        results.append(_execute_one(o))
    return results


def _execute_one(o: Op) -> dict:
    fds: list[int] = []
    try:
        # Validación previa: symlink interno; escape de la raíz ya filtrado en build.
        parent_fd, name, fds = _open_parents(o.repo_root, o.path)
        if o.is_link:
            target = os.readlink(o.src)
            resolved = os.path.normpath(os.path.join(o.dev_root, os.path.dirname(o.path), target))
            if not _inside(o.dev_root, resolved) or not _real_inside(o.dev_root, resolved):
                return {"path": o.path, "status": "bloqueada", "detail": "symlink_externo_rechazado"}
            try:
                os.symlink(target, name, dir_fd=parent_fd)
            except FileExistsError:
                return {"path": o.path, "status": "bloqueada", "detail": "destino_aparecio"}
            return {"path": o.path, "status": "copiada"}
        # Archivo regular: re-verificar origen.
        if not os.path.lexists(o.src):
            return {"path": o.path, "status": "bloqueada", "detail": "origen_ya_no_existe"}
        if o.src_hash is not None and _sha(o.src) != o.src_hash:
            return {"path": o.path, "status": "bloqueada", "detail": "origen_cambio_desde_analisis"}
        # Copia controlada por FD (sin temporal ni rename).
        with open(o.src, "rb") as src_f:
            data = src_f.read()
        is_new = o.snap_repo_hash is None
        if is_new:
            try:
                fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=parent_fd)
            except FileExistsError:
                return {"path": o.path, "status": "bloqueada", "detail": "destino_aparecio"}
        else:
            try:
                fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent_fd)
            except FileNotFoundError:
                return {"path": o.path, "status": "bloqueada", "detail": "destino_desaparecio"}
            except OSError:
                return {"path": o.path, "status": "bloqueada", "detail": "destino_es_symlink_o_no_regular"}
            st = os.fstat(fd)
            if not __import__("stat").S_ISREG(st.st_mode):
                os.close(fd)
                return {"path": o.path, "status": "bloqueada", "detail": "destino_no_regular"}
            if _sha_fd(fd) != o.snap_repo_hash:
                os.close(fd)
                return {"path": o.path, "status": "bloqueada", "detail": "destino_cambio_desde_analisis"}
            if o.src_hash is not None and _sha(o.src) != o.src_hash:
                os.close(fd)
                return {"path": o.path, "status": "bloqueada", "detail": "origen_cambio_desde_analisis"}
            os.ftruncate(fd, 0)
        try:
            os.write(fd, data)
            os.fchmod(fd, o.src_mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        return {"path": o.path, "status": "copiada"}
    except PathEscape as e:
        return {"path": o.path, "status": "bloqueada", "detail": f"ruta_fuera_del_repo: {e}"}
    except OSError as e:
        if e.errno == errno.ELOOP:
            return {"path": o.path, "status": "bloqueada", "detail": "destino_es_symlink"}
        return {"path": o.path, "status": "error", "detail": str(e)}
    finally:
        for f in fds:
            try:
                os.close(f)
            except OSError:
                pass
