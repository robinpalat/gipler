# Gipler

<p align="center">
  <img src="gipler/assets/gipler_trans.png" alt="Gipler" width="144">
</p>

Gipler is a standalone desktop application for inspecting project workspaces,
configuring recognition sources, reviewing differences, and preparing
explicitly authorized copy operations.

## Run from the project directory

```sh
python -m gipler
```

Gipler opens its main window directly. It loads the last profile used (or the
first available one); when there are no profiles it opens the profile launcher
so you can create or open one. It never creates a profile automatically.

The command-line report and terminal interfaces are also available:

```sh
python -m gipler.cli profile-list
python -m gipler.cli analyze-profile PROFILE_ID
python -m gipler.cli tui --profile PROFILE_ID
```

Installable entry points are `gipler`, `gipler-cli`, and `gipler-tui`.

## Profiles and sources

A profile stores its work directory, ordered recognition sources, exclusions,
and view preferences under the user's Gipler configuration directory. Manage
profiles from the main window through **Perfiles → Cambiar perfil…** (open or
switch) and **Perfiles → Administrar perfil…** (rename, change the work
directory, and manage references). Deleting a profile removes only its
configuration, never the physical directories or their contents. The
comparison window is configured from the selected profile: its navigation is
**Inicio**, dynamic reference tabs, **Excluidos**, and **Indeterminados**. The
administrative pages remain
available when empty; exclusions can be restored without touching workspace
files, and membership review distinguishes unknown, ambiguous, and valid shared
paths. Reference tabs hide identical files initially while retaining them in
the analysis and making them available through the state filters.

The `+` control adds a directory for comparison and, by default, uses that same
directory as a synchronization destination. Advanced options retain recognition
rules, read-only references, alternate destinations, and destination links.
Recognition and destination roles remain independent. Profile references reuse
Gipler's comparison tree, filters, inspector, diff window, selection controller,
report rows, and guarded copy engine.

Adding a reference includes an explicit **Establecer línea de base** review
before it is saved. Gipler records relative paths, types, hashes, sizes, and
permissions for the work directory, the reference, and its destination; it also
records paths already present in other available references. Each snapshot is
tied to that source's stable ID and timestamp; existing references are not
backfilled automatically. Paths already present remain pre-existing or
unrecognized, while paths absent from that source's snapshot and created later
can be offered as new by multiple references. Shared or ambiguous membership
is not silently assigned, and each copy destination must still be selected and
explicitly authorized. References can have their baseline explicitly reset or
removed from **Perfil → Referencias**; Gipler warns that classifications and
proposed operations may change.

## Git controls in reference headers

When a reference directory is itself a Git work tree (a normal `.git`
directory or a gitfile pointing to a separate Git directory), its comparison
header shows the current branch and status summary plus icon-only **Fetch**,
**Pull**, **Commit**, and **Push** actions on the same line as the reference
name. Each reference has its own controls and operates only on its own physical
directory. References that are not Git work trees show no Git controls.

Fetch is read-only for the work tree. Pull uses `git pull --ff-only` and asks
for confirmation; it never merges or discards local changes. Commit uses only
files already prepared in the Git index, expands its message field inside the
header, and never runs `git add`. Push asks for confirmation and reports
authentication, connection, rejection, and divergence errors without rebasing,
merging, or resetting. Status queries are read-only (`GIT_OPTIONAL_LOCKS=0`)
and refresh when a reference is opened, after Git operations, after a Gipler
reanalysis, and periodically while the controls are visible.

Git runs in background QProcesses. Gipler keeps `GIT_TERMINAL_PROMPT=0` for
Git's own prompts, but preserves the system SSH client, `SSH_AUTH_SOCK`,
`SSH_ASKPASS`, and SSH configuration. For a passphrase-protected SSH key that
is not loaded in ssh-agent, Gipler provides a graphical Qt askpass helper (or
uses the user's configured askpass) so the passphrase is requested in a dialog
and never stored by Gipler. HTTPS credential helpers remain supported; no
credentials are written by Gipler.

Git action icons are original embedded SVG drawings in
`gipler/gui/icons.py`, rendered in the active theme color at runtime. No icon
is downloaded and no individual action PNG is distributed.

## Obsolete local configuration

The removed Legacy flow used `~/.config/Gipler/ignore.toml`,
`~/.config/idiomind-sync/` and the `dev-sync.toml` manifests. Gipler no longer
reads them. They are kept untouched for reference; profile analysis only uses
the profile configuration under `~/.config/Gipler/profiles/`.

## Visual identity and desktop integration

The approved visual identity lives in `gipler/assets`:

- `gipler_solid.png` is the Solid master and the single source for the
  application icon, windows, dialogs, taskbar, launcher, and About dialog.
- `gipler_trans.png` is the transparent master reserved for documentation and
  editorial material; the README logo is the only editorial use.

All top-level windows resolve their icon through `gipler.resources` and
`gipler.gui.identity`. To replace the design, overwrite the Solid master and
run the permanent updater from any directory:

```sh
./scripts/update-icons.sh
```

The script regenerates every hicolor size and the `.ico` from the master,
installs the FreeDesktop launcher under the user's XDG directories, updates
existing Gipler desktop copies, and refreshes the icon and launcher caches. It
is idempotent and never uses `sudo`.

Optional commands:

```sh
./scripts/update-icons.sh --restart-panel   # refresh a running XFCE panel
./scripts/update-icons.sh --skip-desktop    # regenerate project assets only
python -m gipler.cli desktop --uninstall    # remove the launcher and icons
```

## Safety

Analysis is read-only. Git status and inventory are read-only; the contextual
Git controls only run Fetch, `Pull --ff-only`, Commit on already-staged files,
and Push, each with the safeguards described above. Profile selection is only
intent: copy operations are prepared with the existing validation and snapshot
checks, and execution still requires explicit authorization.

## Tests

From the project directory:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -t .
```
