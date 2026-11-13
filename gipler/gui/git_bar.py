"""Compact Git controls for a single physical reference header.

The widget is reusable by both profile reference tabs and the main comparison
page.  All Git commands run in a QProcess; the Qt event loop is never blocked.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import replace

from PySide6.QtCore import QEvent, QProcess, QProcessEnvironment, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gipler.gui import icons
from gipler.gui.ssh_support import configure_askpass

from gipler.git_integration import (
    DEFAULT_TIMEOUT,
    DETECT_TIMEOUT,
    STATUS_TIMEOUT,
    GitOperationResult,
    friendly_error,
    parse_remotes,
    parse_status,
)


class ElidedLabel(QLabel):
    """QLabel that paints an ellipsis without losing its full text."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str, tooltip: str | None = None) -> None:  # type: ignore[override]
        self._full_text = str(text or "")
        super().setText(self._full_text)
        self.setToolTip(self._full_text if tooltip is None else tooltip)
        self.update()

    def full_text(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self) -> QSize:  # type: ignore[override]
        hint = super().sizeHint()
        return QSize(0, hint.height())

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        metrics = self.fontMetrics()
        available = max(0, self.width() - 2)
        text = metrics.elidedText(self._full_text, Qt.ElideRight, available)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            self.rect(),
            int(self.alignment() | Qt.AlignVCenter),
            text,
        )


class GitProcessController(QProcess):
    """Run Git commands asynchronously and report plain results."""

    status_ready = Signal(object)  # GitStatus | None
    operation_finished = Signal(object)  # GitOperationResult
    busy_changed = Signal(bool)

    def __init__(self, repository: str, parent=None):
        super().__init__(parent)
        self.repository = repository
        self._purpose = ""
        self._kind = ""
        self._message = ""
        self._timed_out = False
        self._timeout = DEFAULT_TIMEOUT
        self._pending_status = None
        self._closing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self.finished.connect(self._on_finished)
        self.errorOccurred.connect(self._on_error)
        self.setProcessChannelMode(QProcess.SeparateChannels)

    @property
    def busy(self) -> bool:
        return self.state() != QProcess.NotRunning

    @property
    def status_in_progress(self) -> bool:
        return self.busy and self._purpose in ("detect", "status", "remotes")

    @property
    def operation_in_progress(self) -> bool:
        return self.busy and self._purpose in ("operation", "check_staged")

    def set_repository(self, repository: str) -> None:
        if repository == self.repository:
            return
        self.shutdown()
        self.repository = repository
        self._pending_status = None

    def refresh_status(self) -> None:
        if self.busy:
            return
        self._start(
            "detect",
            ["rev-parse", "--show-toplevel"],
            timeout=DETECT_TIMEOUT,
            optional_locks=True,
        )

    def fetch(self) -> None:
        self._start_operation("fetch", ["fetch"])

    def pull(self) -> None:
        self._start_operation("pull", ["pull", "--ff-only"])

    def push(self) -> None:
        self._start_operation("push", ["push"])

    def commit(self, message: str) -> None:
        clean = (message or "").strip()
        if not clean:
            self.operation_finished.emit(
                GitOperationResult(
                    kind="commit",
                    repository=self.repository,
                    ok=False,
                    message="El mensaje del commit no puede estar vacío.",
                )
            )
            return
        if self.busy:
            self.operation_finished.emit(
                GitOperationResult(
                    kind="commit",
                    repository=self.repository,
                    ok=False,
                    message="Hay una operación Git en curso. Espere a que termine.",
                )
            )
            return
        self._start(
            "check_staged",
            ["diff", "--cached", "--name-only", "-z"],
            kind="commit",
            message=clean,
            timeout=STATUS_TIMEOUT,
            optional_locks=True,
        )

    def shutdown(self) -> None:
        self._timer.stop()
        self._closing = True
        try:
            if self.state() != QProcess.NotRunning:
                self.kill()
                self.waitForFinished(1000)
        finally:
            self._purpose = ""
            self._kind = ""
            self._message = ""
            self._timed_out = False
            self._pending_status = None

    def _start_operation(self, kind: str, args: list[str]) -> None:
        if self.busy:
            self.operation_finished.emit(
                GitOperationResult(
                    kind=kind,
                    repository=self.repository,
                    ok=False,
                    message="Hay una operación Git en curso. Espere a que termine.",
                )
            )
            return
        self._start("operation", args, kind=kind, timeout=DEFAULT_TIMEOUT, no_prompt=True)

    def _start(
        self,
        purpose: str,
        args: list[str],
        *,
        kind: str = "",
        message: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        optional_locks: bool = False,
        no_prompt: bool = False,
    ) -> None:
        git = shutil.which("git")
        if git is None:
            self._emit_unavailable(purpose, kind)
            return
        self._closing = False
        self._purpose = purpose
        self._kind = kind
        self._message = message
        self._timed_out = False
        self._timeout = timeout
        env = QProcessEnvironment.systemEnvironment()
        env.insert("LC_ALL", "C")
        if optional_locks:
            env.insert("GIT_OPTIONAL_LOCKS", "0")
        if no_prompt:
            env.insert("GIT_TERMINAL_PROMPT", "0")
            ssh_env = configure_askpass(dict(os.environ))
            for key in ("SSH_ASKPASS", "SSH_ASKPASS_REQUIRE"):
                if ssh_env.get(key):
                    env.insert(key, ssh_env[key])
        self.setProcessEnvironment(env)
        self.setProgram(git)
        self.setArguments(["-C", self.repository, *args])
        self._timer.start(timeout * 1000)
        self.start()
        self.busy_changed.emit(True)

    def _emit_unavailable(self, purpose: str, kind: str) -> None:
        message = "No se encontró el ejecutable Git en el sistema."
        if purpose in ("detect", "status", "remotes"):
            self._pending_status = None
            self.status_ready.emit(None)
        else:
            self.operation_finished.emit(
                GitOperationResult(
                    kind=kind or "git",
                    repository=self.repository,
                    ok=False,
                    message=message,
                )
            )

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        self._timer.stop()
        if self._closing:
            self._purpose = ""
            self._kind = ""
            self._message = ""
            self._timed_out = False
            self._pending_status = None
            self.busy_changed.emit(False)
            return
        stdout = bytes(self.readAllStandardOutput()).decode("utf-8", "replace")
        stderr = bytes(self.readAllStandardError()).decode("utf-8", "replace")
        timed_out = self._timed_out
        purpose, kind, message = self._purpose, self._kind, self._message
        self._purpose = ""
        self._kind = ""
        self._message = ""
        self._timed_out = False
        self.busy_changed.emit(False)

        if timed_out:
            self._emit_timeout(purpose, kind)
            return
        if purpose == "detect":
            if exit_code == 0 and self._is_top_level(stdout):
                self._start(
                    "status",
                    [
                        "status",
                        "--porcelain=v2",
                        "--branch",
                        "--untracked-files=normal",
                        "-z",
                    ],
                    timeout=STATUS_TIMEOUT,
                    optional_locks=True,
                )
            else:
                self._pending_status = None
                self.status_ready.emit(None)
            return
        if purpose == "status":
            if exit_code != 0:
                self._pending_status = None
                self.status_ready.emit(None)
                return
            self._pending_status = parse_status(self.repository, stdout)
            self._start(
                "remotes",
                ["remote", "-v"],
                timeout=STATUS_TIMEOUT,
                optional_locks=True,
            )
            return
        if purpose == "remotes":
            pending = self._pending_status
            self._pending_status = None
            if pending is None:
                self.status_ready.emit(None)
                return
            if exit_code == 0:
                names, urls = parse_remotes(stdout)
                pending = replace(
                    pending, remotes=names, remote_urls=urls
                )
            self.status_ready.emit(pending)
            return
        if purpose == "check_staged":
            if exit_code != 0:
                self.operation_finished.emit(
                    GitOperationResult(
                        kind="commit",
                        repository=self.repository,
                        ok=False,
                        message=friendly_error("commit", stderr, stdout, exit_code),
                        stdout=stdout,
                        stderr=stderr,
                        returncode=exit_code,
                    )
                )
                return
            if not stdout.replace("\0", "").strip():
                self.operation_finished.emit(
                    GitOperationResult(
                        kind="commit",
                        repository=self.repository,
                        ok=False,
                        message=(
                            "No hay archivos preparados para el commit. "
                            "Prepare archivos en el índice Git antes de confirmar."
                        ),
                    )
                )
                return
            self._start(
                "operation",
                ["commit", "-m", message],
                kind="commit",
                timeout=DEFAULT_TIMEOUT,
                no_prompt=True,
            )
            return
        if purpose == "operation":
            ok = exit_code == 0
            text = (
                {
                    "fetch": "Fetch completado.",
                    "pull": "Pull completado.",
                    "commit": "Commit creado.",
                    "push": "Push completado.",
                }.get(kind, "Operación completada.")
                if ok
                else friendly_error(kind, stderr, stdout, exit_code)
            )
            self.operation_finished.emit(
                GitOperationResult(
                    kind=kind,
                    repository=self.repository,
                    ok=ok,
                    message=text,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=exit_code,
                    refresh_comparison=ok and kind in ("pull", "commit"),
                )
            )

    def _is_top_level(self, stdout: str) -> bool:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            return False
        try:
            return os.path.normcase(os.path.realpath(lines[-1])) == os.path.normcase(
                os.path.realpath(self.repository)
            )
        except OSError:
            return False

    def _emit_timeout(self, purpose: str, kind: str) -> None:
        message = (
            f"Git no respondió en {self._timeout} segundos. "
            "La operación se detuvo sin descartar cambios."
        )
        if purpose in ("detect", "status", "remotes"):
            self._pending_status = None
            self.status_ready.emit(None)
        else:
            self.operation_finished.emit(
                GitOperationResult(
                    kind=kind or "git",
                    repository=self.repository,
                    ok=False,
                    message=message,
                )
            )

    def _on_timeout(self) -> None:
        if self.state() != QProcess.NotRunning:
            self._timed_out = True
            self.kill()

    def _on_error(self, error) -> None:
        if self._closing or error != QProcess.FailedToStart:
            return
        self._timer.stop()
        purpose, kind = self._purpose, self._kind
        self._purpose = ""
        self._kind = ""
        self._message = ""
        self._pending_status = None
        self.busy_changed.emit(False)
        self._emit_unavailable(purpose, kind)


class GitBar(QWidget):
    """Header controls with branch/status and fetch/pull/commit/push actions."""

    message = Signal(str)
    repository_changed = Signal(str)
    status_changed = Signal(object)

    def __init__(self, repository: str, parent=None):
        super().__init__(parent)
        self.repository = os.path.abspath(os.path.expanduser(repository)) if repository else ""
        self._status = None
        self._available = False
        self._status_checked = False
        self._active = False
        self.controller = GitProcessController(self.repository, self)
        self.controller.status_ready.connect(self._on_status)
        self.controller.operation_finished.connect(self._on_operation_finished)
        self.controller.busy_changed.connect(self._on_busy)
        self._last_icon_color = icons.current_color()
        self._icon_refresh_pending = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(15000)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_after_operation = QTimer(self)
        self._refresh_after_operation.setSingleShot(True)
        self._refresh_after_operation.timeout.connect(self.refresh_status)
        self._build_ui()
        self.setVisible(False)

    # -- construction --------------------------------------------------
    def _build_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.status_label = ElidedLabel("Git")
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setAccessibleName("Estado Git de la referencia")
        row.addWidget(self.status_label, 1)

        self.fetch_button = self._action_button(
            "fetch",
            "Fetch: actualizar referencias remotas sin integrar cambios",
            self.fetch,
            icon_size=18,
        )
        self.pull_button = self._action_button(
            "pull",
            "Pull --ff-only: integrar sólo si es fast-forward",
            self.pull,
            icon_size=18,
        )
        self.commit_button = self._action_button(
            "commit",
            "Commit: confirmar sólo los archivos ya preparados",
            self.begin_commit,
            icon_size=18,
        )
        self.push_button = self._action_button(
            "push",
            "Push: enviar los commits locales al remoto",
            self.push,
            icon_size=18,
        )
        self.action_buttons = [
            self.fetch_button,
            self.pull_button,
            self.commit_button,
            self.push_button,
        ]
        self._base_tooltips = {
            button: button.toolTip() for button in self.action_buttons
        }
        row.addWidget(self.fetch_button)
        row.addWidget(self.pull_button)
        separator = QWidget()
        separator.setFixedWidth(1)
        separator.setFixedHeight(18)
        separator.setBackgroundRole(QPalette.ColorRole.Mid)
        separator.setAutoFillBackground(True)
        row.addWidget(separator)
        row.addWidget(self.commit_button)
        row.addWidget(self.push_button)
        outer.addLayout(row)

        self.commit_row = QWidget(self)
        commit_layout = QHBoxLayout(self.commit_row)
        commit_layout.setContentsMargins(0, 0, 0, 0)
        commit_layout.setSpacing(2)
        self.commit_edit = QLineEdit()
        self.commit_edit.setPlaceholderText("Mensaje del commit...")
        self.commit_edit.setAccessibleName("Mensaje del commit")
        self.commit_edit.returnPressed.connect(self._confirm_commit)
        self.commit_edit.textChanged.connect(self._clear_commit_error)
        self.commit_accept = self._action_button(
            "check",
            "Confirmar commit con los archivos preparados",
            self._confirm_commit,
        )
        self.commit_cancel = self._action_button(
            "cancel",
            "Cancelar el commit sin ejecutar ninguna operación",
            self.cancel_commit,
        )
        commit_layout.addWidget(self.commit_edit, 1)
        commit_layout.addWidget(self.commit_accept)
        commit_layout.addWidget(self.commit_cancel)
        outer.addWidget(self.commit_row)
        self.commit_row.setVisible(False)

        self.commit_error = ElidedLabel()
        self.commit_error.setTextFormat(Qt.PlainText)
        self.commit_error.setWordWrap(False)
        error_palette = self.commit_error.palette()
        error_palette.setColor(QPalette.ColorRole.WindowText, QColor("#C0504D"))
        self.commit_error.setPalette(error_palette)
        self.commit_error.setVisible(False)
        outer.addWidget(self.commit_error)
        self._update_controls()

    def _refresh_icons(self, *, force: bool = False) -> None:
        color = icons.current_color()
        if not force and color == self._last_icon_color:
            return
        self._last_icon_color = color
        for button, name in (
            (self.fetch_button, "fetch"),
            (self.pull_button, "pull"),
            (self.commit_button, "commit"),
            (self.push_button, "push"),
            (self.commit_accept, "check"),
            (self.commit_cancel, "cancel"),
        ):
            button.setIcon(icons.icon(name))

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            if self._icon_refresh_pending:
                return
            self._icon_refresh_pending = True
            QTimer.singleShot(0, self._refresh_icons_deferred)

    def _refresh_icons_deferred(self) -> None:
        self._icon_refresh_pending = False
        self._refresh_icons()

    def _action_button(
        self, icon_name: str, tooltip: str, slot, icon_size: int = 18
    ) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(icons.icon(icon_name))
        button.setIconSize(QSize(icon_size, icon_size))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setFixedSize(28, 28)
        button.setStyleSheet(
            "QToolButton { border: none; background: transparent; padding: 0px; }"
            " QToolButton:hover { background: rgba(127, 127, 127, 0.12);"
            " border-radius: 4px; }"
            " QToolButton:pressed { background: rgba(127, 127, 127, 0.18); }"
        )
        button.clicked.connect(slot)
        return button

    # -- lifecycle -----------------------------------------------------
    @property
    def available(self) -> bool:
        return self._available

    @property
    def status(self):
        return self._status

    @property
    def status_checked(self) -> bool:
        return self._status_checked

    @property
    def commit_expanded(self) -> bool:
        return self.commit_row.isVisible()

    def set_repository(self, repository: str) -> None:
        new_path = os.path.abspath(os.path.expanduser(repository)) if repository else ""
        if new_path == self.repository:
            return
        self.controller.shutdown()
        self.repository = new_path
        self.controller.set_repository(new_path)
        self._status = None
        self._available = False
        self._status_checked = False
        self.cancel_commit()
        self.setVisible(False)
        self._update_controls()
        if self._active:
            self.refresh_status()

    def activate(self) -> None:
        if self._active:
            return
        self._active = True
        self._refresh_timer.start()
        self.refresh_status()

    def deactivate(self) -> None:
        self._active = False
        self._refresh_timer.stop()
        self.collapse_commit()

    def refresh_status(self) -> None:
        if not self.repository:
            self._on_status(None)
            return
        self.controller.refresh_status()

    def _auto_refresh(self) -> None:
        if (
            self._active
            and self.isVisible()
            and self._available
            and not self.controller.busy
        ):
            self.refresh_status()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._active:
            self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        self._refresh_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self._refresh_after_operation.stop()
        self.controller.shutdown()
        super().closeEvent(event)

    # -- status --------------------------------------------------------
    def _on_status(self, status) -> None:
        previous = self._status
        self._status = status
        self._status_checked = True
        self._available = status is not None
        if status is None:
            self.setVisible(False)
            self.collapse_commit()
            self._update_controls()
            if previous is not None:
                self.status_changed.emit(None)
            return
        if status == previous:
            self.setVisible(self.isEnabled())
            self._update_controls()
            return
        self.status_label.setText(status.summary, self._status_tooltip(status))
        self.setVisible(self.isEnabled())
        self.status_changed.emit(status)
        self._update_controls()

    def _status_tooltip(self, status) -> str:
        upstream = status.upstream or (
            "sin remoto configurado" if not status.has_remote else "sin upstream"
        )
        urls = ", ".join(status.remote_urls) if status.remote_urls else "sin URL"
        return (
            f"Repositorio: {status.repository}\n"
            f"Rama: {status.branch or ('HEAD desprendida' if status.detached else 'sin rama')}\n"
            f"Upstream: {upstream}\n"
            f"Remotos: {urls}\n"
            f"Preparados: {status.staged} · Modificados: {status.modified} · "
            f"Sin seguimiento: {status.untracked} · Conflictos: {status.unmerged}"
        )

    def _on_busy(self, busy: bool) -> None:
        if busy:
            self._refresh_timer.stop()
        elif self._active and self.isVisible():
            self._refresh_timer.start()
        if not busy:
            if self._status is not None:
                self.status_label.setText(
                    self._status.summary, self._status_tooltip(self._status)
                )
            else:
                self.status_label.setText("Git")
        self._update_controls()
        if busy and self.controller.operation_in_progress:
            tooltip = (
                self._status_tooltip(self._status)
                if self._status is not None
                else "Operación Git en curso."
            )
            self.status_label.setText("Git: operación en curso…", tooltip)

    def _set_tooltip(self, button: QToolButton, reason: str = "") -> None:
        text = self._base_tooltips[button]
        if reason:
            text = f"{text}\n{reason}"
        button.setToolTip(text)
        button.setAccessibleName(text)

    def _can_fetch(self) -> bool:
        return (
            self._available
            and self.isEnabled()
            and not self.controller.busy
            and self._status is not None
            and self._status.has_remote
        )

    def _can_pull(self) -> bool:
        return (
            self._can_fetch()
            and bool(self._status and self._status.upstream)
            and not (self._status and self._status.unmerged)
        )

    def _can_push(self) -> bool:
        return self._can_pull()

    def _can_commit(self) -> bool:
        return (
            self._available
            and self.isEnabled()
            and not self.controller.busy
            and self._status is not None
            and self._status.staged > 0
            and self._status.unmerged == 0
        )

    def _update_controls(self) -> None:
        status = self._status
        ready = self._available and not self.controller.busy and self.isEnabled()
        has_remote = bool(status and status.has_remote)
        has_upstream = bool(status and status.upstream and status.has_remote)
        conflicts = bool(status and status.unmerged)
        staged = bool(status and status.staged)
        fetch_enabled = ready and has_remote
        pull_enabled = ready and has_upstream and not conflicts
        push_enabled = pull_enabled
        commit_enabled = ready and staged and not conflicts

        self.fetch_button.setEnabled(fetch_enabled)
        self.pull_button.setEnabled(pull_enabled)
        self.commit_button.setEnabled(commit_enabled)
        self.push_button.setEnabled(push_enabled)
        self.commit_edit.setEnabled(commit_enabled)
        self.commit_accept.setEnabled(commit_enabled)
        self.commit_cancel.setEnabled(ready)

        busy_reason = (
            "Operación Git en curso." if self.controller.busy else ""
        )
        if not status:
            unavailable = "Git no disponible en esta referencia."
        else:
            unavailable = ""
        self._set_tooltip(
            self.fetch_button,
            busy_reason
            or unavailable
            or ("No hay remoto configurado." if not has_remote else ""),
        )
        self._set_tooltip(
            self.pull_button,
            busy_reason
            or unavailable
            or (
                "Pull bloqueado: hay conflictos sin resolver."
                if conflicts
                else "La rama actual no tiene upstream."
                if not has_upstream
                else ""
            ),
        )
        self._set_tooltip(
            self.commit_button,
            busy_reason
            or unavailable
            or (
                "Commit bloqueado: hay conflictos sin resolver."
                if conflicts
                else "No hay archivos preparados; prepare archivos en Git."
                if not staged
                else ""
            ),
        )
        self._set_tooltip(
            self.push_button,
            busy_reason
            or unavailable
            or (
                "Push bloqueado: hay conflictos sin resolver."
                if conflicts
                else "La rama actual no tiene upstream."
                if not has_upstream
                else ""
            ),
        )

    # -- operations ----------------------------------------------------
    def fetch(self) -> None:
        if not self._can_fetch():
            return
        self.message.emit("Ejecutando git fetch…")
        self.controller.fetch()

    def pull(self) -> None:
        if not self._can_pull():
            return
        answer = QMessageBox.question(
            self,
            "Pull",
            f"¿Ejecutar git pull --ff-only en\n{self.repository}?\n\n"
            "No se harán merges automáticos ni se descartarán cambios locales.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.message.emit("Ejecutando git pull --ff-only…")
        self.controller.pull()

    def push(self) -> None:
        if not self._can_push():
            return
        answer = QMessageBox.question(
            self,
            "Push",
            f"¿Ejecutar git push en\n{self.repository}?\n\n"
            "No se hará rebase, merge ni reset si el remoto ha divergido.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.message.emit("Ejecutando git push…")
        self.controller.push()

    def begin_commit(self) -> None:
        if not self._can_commit():
            status = self._status
            if status is not None and status.unmerged:
                reason = "Commit bloqueado: hay conflictos sin resolver."
            elif status is not None and not status.staged:
                reason = "No hay archivos preparados; prepare archivos en Git."
            else:
                reason = "Commit no disponible en este momento."
            self._show_commit_error(reason)
            return
        self.commit_error.setVisible(False)
        self.commit_row.setVisible(True)
        self.commit_edit.setFocus()

    def collapse_commit(self) -> None:
        self.commit_error.setVisible(False)
        self.commit_row.setVisible(False)

    def cancel_commit(self) -> None:
        self.collapse_commit()
        self.commit_edit.clear()

    def _confirm_commit(self) -> None:
        message = self.commit_edit.text().strip()
        if not message:
            self._show_commit_error("El mensaje del commit no puede estar vacío.")
            return
        if not self._can_commit():
            status = self._status
            if status is not None and status.unmerged:
                reason = "Commit bloqueado: hay conflictos sin resolver."
            elif status is not None and not status.staged:
                reason = "No hay archivos preparados; prepare archivos en Git."
            else:
                reason = "Commit no disponible en este momento."
            self._show_commit_error(reason)
            return
        self.commit_error.setVisible(False)
        self.controller.commit(message)

    def _show_commit_error(self, text: str) -> None:
        self.commit_error.setText(text)
        self.commit_error.setToolTip(text)
        self.commit_error.setVisible(True)
        self.message.emit(f"Commit no realizado: {text}")

    def _clear_commit_error(self) -> None:
        if self.commit_error.isVisible():
            self.commit_error.setVisible(False)

    def _on_operation_finished(self, result: GitOperationResult) -> None:
        if result.kind == "commit":
            if result.ok:
                self.commit_error.setVisible(False)
                self.commit_row.setVisible(False)
                self.commit_edit.clear()
                self.message.emit(result.message)
                if result.refresh_comparison:
                    self.repository_changed.emit(self.repository)
                self._refresh_after_operation.start(0)
            else:
                self._show_commit_error(result.message)
            return
        if result.ok:
            self.message.emit(result.message)
            if result.refresh_comparison:
                self.repository_changed.emit(self.repository)
            self._refresh_after_operation.start(0)
        else:
            message = result.message
            status = self._status
            if (
                status is not None
                and status.uses_https_remote
                and "autenticar" in message
            ):
                message = (
                    f"{message}\nEl remoto usa HTTPS: configure un credential "
                    "helper o un token de acceso; el agente SSH no interviene."
                )
            self.message.emit(f"Git: {message}")
            QMessageBox.warning(self, "Git", message)
            self.refresh_status()
