# Gipler

Gipler is a standalone desktop application for inspecting project workspaces,
configuring recognition sources, reviewing differences, and preparing
explicitly authorized copy operations.

## Run from the project directory

```sh
python -m gipler
```

Gipler opens its main window directly. It loads the last profile used (or the
first available one); when there are no profiles it opens an empty main window
with the **Perfiles → Administrar perfiles…** menu available. It never creates a
profile automatically.

The command-line report and terminal interfaces are also available:

```sh
python -m gipler.cli analyze
python -m gipler.cli tui
python -m gipler.cli profile-list
python -m gipler.cli analyze-profile PROFILE_ID
python -m gipler.cli tui --profile PROFILE_ID
```

Installable entry points are `gipler`, `gipler-cli`, `gipler-tui`, and
`gipler-legacy`.

## Profiles and sources

A profile stores its work directory, ordered recognition sources, exclusions,
and view preferences under the user's Gipler configuration directory. Manage
profiles from the main window through **Perfiles → Administrar perfiles…**:
create, open, switch, rename, edit, or delete them (deleting a profile removes
only its configuration, never the physical directories or their contents). The original comparison window is configured
from the selected profile: its navigation is **Inicio**, dynamic reference tabs,
`+`, **Excluidos**, and **Indeterminados**. The administrative pages remain
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

## Legacy flow (Dev/Principal/Add-ons)

The original fixed Dev/Principal/Add-ons flow is still available from a
terminal, using the same code and configuration as before:

```sh
gipler-legacy
```

If the package is not installed, use the repository launcher from the project
directory (or invoke it by absolute path, which also works from any directory):

```sh
./run-gipler-legacy
```

Its configuration and exclusions are preserved; profile analysis does not
rewrite or migrate those settings. This command opens only the legacy flow and
does not touch the profile system.

## Desktop integration

The official icon ships inside the package (`gipler/assets`) and is applied to
the application window, so it appears in the taskbar and in Alt+Tab.

Install the FreeDesktop launcher and the icon sizes under the user's XDG
directories:

```sh
python -m gipler.cli desktop
python -m gipler.cli desktop --uninstall
```

Regenerate the packaged sizes from the master `gipler.png` with
`python tools/gen_icons.py`.

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
