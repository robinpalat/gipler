"""Terminal entry point for the original Dev/Principal/Add-ons flow."""
from __future__ import annotations


def main() -> int:
    from gipler.gui.main_window import create_application, launch_legacy_ui

    return launch_legacy_ui(create_application())


if __name__ == "__main__":
    raise SystemExit(main())
