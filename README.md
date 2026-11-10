# Gipler

Gipler is a standalone desktop application for analyzing configured source and
repository directories, reviewing differences, and preparing explicitly
authorized copy operations.

## Run from the project directory

```sh
python -m gipler
```

The command-line report and terminal interfaces are also available:

```sh
python -m gipler.cli analyze
python -m gipler.cli tui
```

Installable entry points are `gipler`, `gipler-cli`, and `gipler-tui`.

## Configure directories

Use **Herramientas → Configuración** in the GUI to set the Dev source, Principal
repository, and Add-ons repository. The paths are external to the application
installation and are saved in the user's Gipler settings. CLI options
`--dev`, `--principal`, and `--addons` override those settings for one run.

Application preferences and local exclusions are stored in the user's
configuration directory.

## Safety

Analysis is read-only. Git is queried only for status and inventory. Copy
operations are prepared through the existing safety checks and require explicit
authorization in the GUI.

## Tests

From the project directory:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -t .
```
