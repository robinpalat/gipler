"""Embedded SVG icon and SSH askpass integration tests."""
from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gipler.gui import icons, ssh_askpass
from gipler.gui.ssh_support import configure_askpass, gui_available
from gipler.git_integration import friendly_error

APP = QApplication.instance() or QApplication([])


class EmbeddedIconTests(unittest.TestCase):
    def test_git_icons_are_embedded_and_render(self):
        self.assertTrue(
            {"fetch", "pull", "commit", "push"}.issubset(set(icons.ICON_NAMES))
        )
        for name in icons.ICON_NAMES:
            source = icons.svg_source(name, "#123456")
            self.assertIn("<svg", source)
            self.assertIn("#123456", source)
            self.assertIn('stroke-width="1.4"', source)
            self.assertNotIn("<image", source)
            self.assertNotIn("base64", source)
            pixmap = icons.icon(name).pixmap(QSize(16, 16))
            self.assertFalse(pixmap.isNull())
            self.assertGreater(pixmap.width(), 0)
            self.assertFalse(
                QIcon(icons.icon(name)).pixmap(QSize(20, 20)).isNull()
            )

    def test_icon_color_can_be_overridden_and_disabled_mode_exists(self):
        source = icons.svg_source("pull", "#ABCDEF")
        self.assertIn("#ABCDEF", source)
        icon = icons.icon("pull", "#ABCDEF")
        self.assertFalse(icon.pixmap(QSize(16, 16), QIcon.Mode.Disabled).isNull())

    def test_unknown_icon_is_rejected(self):
        with self.assertRaises(KeyError):
            icons.icon("does-not-exist")


class ApplicationIdentityTests(unittest.TestCase):
    def test_top_level_dialogs_use_solid_application_icon(self):
        from gipler.gui.about_dialog import AboutDialog
        from gipler.gui.identity import application_icon
        from gipler.gui.operations_dialog import OperationsDialog

        expected = application_icon()
        self.assertFalse(expected.isNull())
        for dialog in (AboutDialog(), OperationsDialog()):
            self.assertEqual(dialog.windowIcon().cacheKey(), expected.cacheKey())
            dialog.deleteLater()


class SshSupportTests(unittest.TestCase):
    def test_existing_askpass_is_preserved(self):
        env = {
            "DISPLAY": ":0",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "SSH_ASKPASS": "/usr/bin/custom-askpass",
            "SSH_ASKPASS_REQUIRE": "never",
            "HOME": "/tmp/home",
        }
        result = configure_askpass(env)
        self.assertEqual(result["SSH_ASKPASS"], "/usr/bin/custom-askpass")
        self.assertEqual(result["SSH_ASKPASS_REQUIRE"], "never")
        self.assertEqual(result["SSH_AUTH_SOCK"], "/tmp/agent.sock")
        self.assertEqual(result["HOME"], "/tmp/home")

    def test_missing_askpass_uses_gipler_helper(self):
        env = {"DISPLAY": ":0", "SSH_AUTH_SOCK": "/tmp/agent.sock"}
        with patch(
            "gipler.gui.ssh_support.askpass_helper_path",
            return_value="/tmp/gipler-askpass",
        ):
            result = configure_askpass(env)
        self.assertEqual(result["SSH_ASKPASS"], "/tmp/gipler-askpass")
        self.assertEqual(result["SSH_ASKPASS_REQUIRE"], "force")
        self.assertEqual(result["SSH_AUTH_SOCK"], "/tmp/agent.sock")

    def test_no_graphical_session_leaves_environment_untouched(self):
        env = {"QT_QPA_PLATFORM": "offscreen", "SSH_AUTH_SOCK": "/tmp/a"}
        self.assertFalse(gui_available(env))
        self.assertEqual(configure_askpass(env), env)

    def test_askpass_helper_reads_secret_without_storing_it(self):
        with patch.object(
            ssh_askpass, "_passphrase", return_value=("secreto-temporal", True)
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = ssh_askpass.main(["gipler-askpass", "Passphrase:"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "secreto-temporal\n")

    def test_ssh_auth_error_is_actionable(self):
        message = friendly_error(
            "fetch",
            "git@github.com: Permission denied (publickey).",
        )
        self.assertIn("SSH", message)
        self.assertIn("passphrase", message)


if __name__ == "__main__":
    unittest.main()
